; =====================================================================
; SmartCook 機械手臂控制程式 — F60_R (右臂 / 輔助固定臂)
; 語言: Kawasaki AS Language (F 控制器)
; 版本: v0.3 (骨架 skeleton)
; 對應規格書: COMMAND_SPECIFICATION.md / CONNECTION_PROTOCOL.md /
;             OBJECT_DEFINITIONS_v1.1.md / SmartCook_信號分配表.docx
;
; 請與 F60_F_左臂.as 對照閱讀，兩者共用同一組雙臂對接 I/O 訊號。
; 通訊/教點待確認事項同 F60_F_左臂.as 開頭說明，此處不重複。
;
; v0.3 雙臂協同架構變更 (與 F60_F_左臂.as 對應):
;   雙臂只用「一組」交握訊號 (sig_out_step/sig_in_step)，PICKUP、
;   CHOP、PLACE(POUR)、FLIP 都改成 PC 端同時明確發指令給 F60_F 與
;   F60_R 兩邊，兩邊各自跑對應的動作，過程中用 SYNC_STEP 逐階段會
;   合，不再依賴 ON...CALL 中斷去被動猜測 F60_F 現在在做什麼——因為
;   共用同一組訊號後，中斷方式無法分辨「這次訊號是取料集中、還是
;   切割壓料、還是裝盤傾倒」，只有雙邊都明確知道自己在跑同一種指令
;   時，才能安全共用同一組訊號。
;
;   前提: PC 端需要把 PICKUP / CHOP / PLACE(POUR) 這三種指令也發送
;   給 F60_R (做法跟現有 FLIP 已經是雙邊各發一次一樣)。這裡的
;   DO_CHOP 是 F60_R 版本的「壓料/步進」角色，不是真的切割。
; =====================================================================

.PROGRAM INIT_CONST()
  $this_arm = "F60_R"

  ; --- TCP 通訊參數 ---
  port = 9000
  max_length = 255
  tout_accept = 5
  tout_recv = 10
  tout_send = 5

  ; --- I/O 訊號編號 (雙臂共用同一組交握訊號，佔位值，待電控確認) ---
  ; 依 AS 語言慣例，外部輸出訊號用小號碼，外部輸入訊號從 1001 起算。
  sig_out_step = 1        ; 輸出: 本臂完成目前階段 → F60_F
  sig_in_step = 1001       ; 輸入: F60_F 完成目前階段 ← F60_F

  ; --- 動作參數 (可依現場試切調整，單位 mm) ---
  appro_mm = 80.0
  press_down_mm = 15.0     ; 壓住食材下壓量 (輕壓，勿過力)
  step_mm = 4.0             ; 壓點隨切割步進距離 (應與 CHOP 厚度一致)
  flip_down_mm = 90.0
  pour_tilt_deg = 90.0
  converge_dx = -20.0      ; PICKUP 集中階段：F60_R 往中心平移量 (與 F60_F 方向相對，待現場確認)
  converge_dy = 0.0

  ; --- 逾時設定 (秒) ---
  timeout_io_sec = 5.0
  timeout_flip_sec = 5.0

  robot_busy = 0
  $rxbuf = ""
.END

; ---------------------------------------------------------------------
; 點位宣告 (PTEACH = 待現場教點，目前為佔位座標)
;
; 除 HOME_RIGHT 外，其餘點皆用複合座標 ORIGIN + TRANS(x,y,z,o,a,t)
; 表示 (說明同 F60_F_左臂.as)。注意: 這裡的 ORIGIN 需在 F60_R 自己
; 的教示盒上另外教一次——即使是同一個物理檯角，F60_R 與 F60_F 是
; 兩台獨立控制器，各自基座座標系不同，數值不能沿用對方教好的值。
;
; PICKUP_CUCUMBER / PICKUP_ROMAINE 是 v0.3 新增：因為現在三種食材
; 取料都是雙臂協同，F60_R 也需要各取料點對應的位置 (從右臂這一側
; 接近同一個實體取料點)，不再只有 PICKUP_RED_LEAF 一個。
; ---------------------------------------------------------------------
.PROGRAM INIT_POINTS()
  POINT ORIGIN = TRANS(0,0,0,0,0,0)   ; PTEACH: 檯面左下角基準點 (F60_R 自身基座座標系)

  ; --- 以下 X,Y,Z,Angle 皆為佔位 0，待 CALIBRATION_POINTS.csv 標定完成後填入 ---
  POINT PICKUP_CUCUMBER = ORIGIN + TRANS(0,0,0,0,0,0)   ; X,Y,Z,Angle ← CSV
  POINT PICKUP_ROMAINE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z,Angle ← CSV
  POINT PICKUP_RED_LEAF = ORIGIN + TRANS(0,0,0,0,0,0)   ; X,Y,Z,Angle ← CSV (雙鏟協作聚攏)
  POINT PRESS_CHOP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)   ; 對應 WORK_CHOP_ZONE 的壓點偏移
  POINT MIX_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)          ; X,Y,Z ← CSV
  POINT WORK_FLIP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z ← CSV
  POINT SALAD_BOWL = ORIGIN + TRANS(0,0,0,0,0,0)        ; X,Y,Z ← CSV (ArUco ID 102 輔助標定)

  ; HOME_RIGHT 在相機拍不到的高處，與檯面座標系無關，維持獨立絕對點
  POINT HOME_RIGHT = TRANS(0,0,0,0,0,0)   ; PTEACH (手工標定，示教盒)
.END

; ---------------------------------------------------------------------
; 刀具座標設定 (TOOL)，說明同 F60_F_左臂.as。
; ---------------------------------------------------------------------
.PROGRAM INIT_TOOL()
  BASE NULL
  POINT RIGHT_SPATULA = TRANS(0,0,0,0,0,0)   ; PTEACH: 右鏟(平面)相對法蘭面的偏移，待量測/教點
  TOOL RIGHT_SPATULA
.END

; =====================================================================
; MAIN — 程式進入點 (PC 指令通道)
; =====================================================================
.PROGRAM MAIN()
  CALL INIT_CONST
  CALL INIT_POINTS
  CALL INIT_TOOL
  SPEED 30 ALWAYS
  ACCURACY 1
  SIGNAL -sig_out_step
  LMOVE HOME_RIGHT

  CALL OPEN_LISTEN
  DO
    CALL WAIT_ACCEPT(accepted)
    IF accepted == 1 THEN
      $rxbuf = ""
      CALL DO_HANDSHAKE(hs_ok)
      IF hs_ok == 1 THEN
        conn_lost = 0
        DO
          CALL RECV_LINE($line, rok)
          IF rok == 0 THEN
            conn_lost = 1
          ELSE
            CALL SPLIT_CSV($line)
            CALL DISPATCH
          END
        UNTIL conn_lost == 1
      END
      TCP_CLOSE cret, sock_id
    END
  UNTIL 1 == 0
.END

; ---------------------------------------------------------------------
; 開始等待連線 (程式啟動時執行一次，之後重複用同一個 LISTEN 接受新連線)
; ---------------------------------------------------------------------
.PROGRAM OPEN_LISTEN()
  er_count = 0
listen:
  TCP_LISTEN lret, port
  IF lret < 0 THEN
    er_count = er_count + 1
    PRINT "TCP_LISTEN error=", lret, " count=", er_count
    GOTO listen
  END
  PRINT "TCP_LISTEN OK port=", port
.END

; ---------------------------------------------------------------------
; 等待 PC 連線 (TCP_ACCEPT)，.accepted=1 表示已建立連線
; ---------------------------------------------------------------------
.PROGRAM WAIT_ACCEPT(.accepted)
  TCP_ACCEPT sock_id, port, tout_accept, client_ip[1]
  IF sock_id < 0 THEN
    .accepted = 0
  ELSE
    PRINT "TCP_ACCEPT OK id=", sock_id
    .accepted = 1
  END
.END

; ---------------------------------------------------------------------
; 握手: 收到 "connect" 後回覆 "BOARD_ID,F60_CTRL_002"
; ---------------------------------------------------------------------
.PROGRAM DO_HANDSHAKE(.ok)
  CALL RECV_LINE($line, rok)
  IF rok == 0 THEN
    .ok = 0
    RETURN
  END
  IF $line == "connect" THEN
    CALL SEND_LINE("BOARD_ID,F60_CTRL_002")
    .ok = 1
  ELSE
    CALL SEND_LINE("ERROR,E4021")
    .ok = 0
  END
.END

; ---------------------------------------------------------------------
; 讀取一行 CSV 指令 (以 \n 結尾)。.rok=0 代表連線中斷/逾時。
; ---------------------------------------------------------------------
.PROGRAM RECV_LINE(.$line, .rok)
  DO
    nl_pos = INSTR(1, $rxbuf, $CHR(10))
    IF nl_pos > 0 THEN
      .$line = $LEFT($rxbuf, nl_pos - 1)
      $rxbuf = $MID($rxbuf, nl_pos + 1, LEN($rxbuf) - nl_pos)
      .rok = 1
      RETURN
    END
    TCP_RECV rret, sock_id, $recv_buf[1], recv_n, tout_recv, max_length
    IF rret < 0 THEN
      IF rret <> -34024 THEN   ; -34024 = E4024 通信逾時，只是暫時沒新資料，不是斷線
        .rok = 0
        RETURN
      END
    ELSE
      IF recv_n > 0 THEN
        FOR i = 1 TO recv_n
          $rxbuf = $rxbuf + $recv_buf[i]
        END
      END
    END
  UNTIL 1 == 0
.END

; ---------------------------------------------------------------------
; 送出一行回應 (自動加上 \n)
; ---------------------------------------------------------------------
.PROGRAM SEND_LINE(.$msg)
  $send_buf[1] = .$msg + $CHR(10)
  TCP_SEND sret, sock_id, $send_buf[1], 1, tout_send
.END

; ---------------------------------------------------------------------
; CSV 切割: $line → $fld[1..nfld]
; ---------------------------------------------------------------------
.PROGRAM SPLIT_CSV(.$line)
  FOR i = 1 TO 8
    $fld[i] = ""
  END
  nfld = 0
  $rest = .$line
  DO
    p = INSTR(1, $rest, ",")
    nfld = nfld + 1
    IF p == 0 THEN
      $fld[nfld] = $rest
      $rest = ""
    ELSE
      $fld[nfld] = $LEFT($rest, p - 1)
      $rest = $MID($rest, p + 1, LEN($rest) - p)
    END
  UNTIL $rest == "" OR nfld >= 8
.END

; ---------------------------------------------------------------------
; 指令分派
; ---------------------------------------------------------------------
.PROGRAM DISPATCH()
  IF $fld[1] == "HEARTBEAT" THEN
    CALL SEND_LINE("HEARTBEAT_ACK")
    RETURN
  END

  IF robot_busy == 1 THEN
    IF $fld[1] == "STOP" THEN
      CALL DO_STOP
    ELSE
      CALL SEND_LINE("BUSY")
    END
    RETURN
  END

  SCASE $fld[1] OF
  SVALUE "PICKUP":
    CALL DO_PICKUP($fld[2], $fld[3])
  SVALUE "CHOP":
    CALL DO_CHOP($fld[2], VAL($fld[3]), VAL($fld[4]))
  SVALUE "PLACE":
    CALL DO_PLACE($fld[2], $fld[3])
  SVALUE "FLIP":
    CALL DO_FLIP(VAL($fld[2]), VAL($fld[3]))
  SVALUE "HOME":
    CALL DO_HOME($fld[2])
  SVALUE "STOP":
    CALL DO_STOP
  SVALUE "RESET":
    CALL DO_RESET
  SVALUE "STATUS":
    CALL DO_STATUS($fld[2])
  SVALUE "READY":
    CALL DO_READY($fld[2])
  ANY :
    CALL SEND_LINE("ERROR,E4021")
  END
.END

; ---------------------------------------------------------------------
; 訊號等待 (含逾時)，.ok=1 成功 / .ok=0 逾時
; ---------------------------------------------------------------------
.PROGRAM WAIT_SIGNAL(.sig_no, .timeout_sec, .ok)
  TIMER 1 = 0
  WAIT SIG(.sig_no) OR TIMER(1) > .timeout_sec
  IF SIG(.sig_no) THEN
    .ok = 1
  ELSE
    .ok = 0
  END
.END

.PROGRAM WAIT_SIGNAL_OFF(.sig_no, .timeout_sec, .ok)
  TIMER 1 = 0
  WAIT (SIG(.sig_no) == 0) OR TIMER(1) > .timeout_sec
  IF SIG(.sig_no) == 0 THEN
    .ok = 1
  ELSE
    .ok = 0
  END
.END

; ---------------------------------------------------------------------
; SYNC_STEP — 與 F60_F_左臂.as 完全對稱的單階段會合 (barrier)。
; ---------------------------------------------------------------------
.PROGRAM SYNC_STEP(.ok)
  SIGNAL sig_out_step
  CALL WAIT_SIGNAL(sig_in_step, timeout_io_sec, ok1)
  IF ok1 == 0 THEN
    SIGNAL -sig_out_step
    .ok = 0
    RETURN
  END
  SIGNAL -sig_out_step
  CALL WAIT_SIGNAL_OFF(sig_in_step, timeout_io_sec, ok2)
  .ok = ok2
.END

; ---------------------------------------------------------------------
; PICKUP,<LOCATION>,<ARM> — 雙臂協同取料 (F60_R 為配合方)
; ARM 參數固定驗證為 "F60_F"，代表這筆 PICKUP 由 F60_F 主導、F60_R
; 配合。四個階段 (就緒/下降/集中/抬起) 與 DO_PICKUP@F60_F 一一對應。
; ---------------------------------------------------------------------
.PROGRAM DO_PICKUP(.$location, .$arm)
  IF .$arm <> "F60_F" THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END

  found = 1
  IF .$location == "PICKUP_CUCUMBER" THEN
    POINT target_pt = PICKUP_CUCUMBER
  ELSE
    IF .$location == "PICKUP_ROMAINE" THEN
      POINT target_pt = PICKUP_ROMAINE
    ELSE
      IF .$location == "PICKUP_RED_LEAF" THEN
        POINT target_pt = PICKUP_RED_LEAF
      ELSE
        found = 0
      END
    END
  END

  IF found == 0 THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END

  robot_busy = 1
  SPEED 40 ALWAYS

  ; 階段 1: 就緒
  LAPPRO target_pt, appro_mm
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    robot_busy = 0
    RETURN
  END

  ; 階段 2: 下降
  LMOVE target_pt
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    robot_busy = 0
    RETURN
  END

  ; 階段 3: 集中 (方向與 F60_F 相對，佔位示意，待現場調整)
  DRAW converge_dx, converge_dy, 0
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    robot_busy = 0
    RETURN
  END

  ; 階段 4: 抬起
  LDEPART appro_mm
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    robot_busy = 0
    RETURN
  END

  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM> — F60_R 的「壓料/
; 步進」角色 (不切割)。與 DO_CHOP@F60_F 一一對應：F60_F 每下壓一刀
; 就 SYNC_STEP 一次，F60_R 每次會合就壓料+步進一次。
; ---------------------------------------------------------------------
.PROGRAM DO_CHOP(.$food, .cuts, .thick)
  IF .cuts < 1 OR .cuts > 20 OR .thick <= 0 THEN
    CALL SEND_LINE("ERROR,E4005")
    RETURN
  END

  robot_busy = 1
  SPEED 30 ALWAYS
  LAPPRO PRESS_CHOP_ZONE, appro_mm
  LMOVE PRESS_CHOP_ZONE

  i = 0
  DO
    CALL SYNC_STEP(ok)                  ; 等 F60_F 完成本刀下壓
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    DRAW 0, 0, -press_down_mm           ; 壓住食材
    DRAW step_mm, 0, 0                  ; 隨切割步進 (應與 CHOP 厚度一致)
    DRAW 0, 0, press_down_mm            ; 鬆開，準備下一刀
    i = i + 1
  UNTIL i >= .cuts

  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; PLACE,<LOCATION>,<METHOD> — 中間位置托運 (SCOOP) 或沙拉盤傾倒 (POUR)
; ---------------------------------------------------------------------
.PROGRAM DO_PLACE(.$location, .$method)
  found = 1
  IF .$location == "MIX_ZONE" THEN
    POINT target_pt = MIX_ZONE
  ELSE
    IF .$location == "SALAD_BOWL" THEN
      POINT target_pt = SALAD_BOWL
    ELSE
      found = 0
    END
  END

  IF found == 0 THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END
  IF .$method <> "POUR" AND .$method <> "SCOOP" AND .$method <> "PUSH" THEN
    CALL SEND_LINE("ERROR,E4001")
    RETURN
  END

  robot_busy = 1
  SPEED 40 ALWAYS
  LAPPRO target_pt, appro_mm
  LMOVE target_pt

  IF .$method == "POUR" THEN
    CALL SYNC_STEP(ok)                  ; 與 F60_F 會合，一起傾倒
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    TDRAW 0, 0, 0, 0, pour_tilt_deg, 0, 20      ; 雙鏟對合傾倒手勢 (角度依治具調整)
    TDRAW 0, 0, 0, 0, -pour_tilt_deg, 0, 20
  END

  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; FLIP,<NUM_CYCLES>,<SPEED_PERCENT> — 右臂為配合方 (F 上翻時，R 下壓翻)
; ---------------------------------------------------------------------
.PROGRAM DO_FLIP(.cycles, .speed_pct)
  IF .cycles < 1 OR .cycles > 20 THEN
    CALL SEND_LINE("ERROR,E4005")
    RETURN
  END
  IF .speed_pct < 1 OR .speed_pct > 100 THEN
    CALL SEND_LINE("ERROR,E4005")
    RETURN
  END

  robot_busy = 1
  SPEED .speed_pct ALWAYS
  LMOVE WORK_FLIP_ZONE

  i = 0
  DO
    CALL SYNC_STEP(ok)                   ; 與左鏟本循環會合
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    DRAW 0, 0, -flip_down_mm             ; 右鏟下壓並翻
    DRAW 0, 0, flip_down_mm
    i = i + 1
  UNTIL i >= .cycles

  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; HOME,<ARM>
; ---------------------------------------------------------------------
.PROGRAM DO_HOME(.$arm)
  IF .$arm <> $this_arm THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END
  robot_busy = 1
  SPEED 20 ALWAYS
  LMOVE HOME_RIGHT
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; STOP — 緊急停止
; ---------------------------------------------------------------------
.PROGRAM DO_STOP()
  BRAKE
  SIGNAL -sig_out_step
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; RESET — 清除本程式的應用層狀態 (見 F60_F_左臂.as 開頭關於 ERESET
; 限制的說明: 機器人控制程式無法自我 ERESET，此處僅重置忙碌旗標與
; 交握訊號)
; ---------------------------------------------------------------------
.PROGRAM DO_RESET()
  robot_busy = 0
  SIGNAL -sig_out_step
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; STATUS,<ARM> / READY,<ARM>
; ---------------------------------------------------------------------
.PROGRAM DO_STATUS(.$arm)
  IF .$arm <> $this_arm THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END
  IF robot_busy == 1 THEN
    CALL SEND_LINE("BUSY")
  ELSE
    CALL SEND_LINE("OK")
  END
.END

.PROGRAM DO_READY(.$arm)
  IF .$arm <> $this_arm THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END
  IF robot_busy == 1 THEN
    CALL SEND_LINE("BUSY")
  ELSE
    CALL SEND_LINE("OK")
  END
.END
