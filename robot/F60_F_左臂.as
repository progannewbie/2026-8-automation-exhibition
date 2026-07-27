; =====================================================================
; SmartCook 機械手臂控制程式 — F60_F (左臂 / 主切割臂)
; 語言: Kawasaki AS Language (F 控制器)
; 版本: v0.2 (骨架 skeleton)
; 對應規格書: COMMAND_SPECIFICATION.md / CONNECTION_PROTOCOL.md /
;             OBJECT_DEFINITIONS_v1.1.md / SmartCook_信號分配表.docx
;
; 語法依據: 90209-1025 AS Language Reference Manual (motion/structure/
;           signal instructions) 與 90210-1344 通信選項手冊 1.6 節
;           (TCP_LISTEN/TCP_ACCEPT/TCP_SEND/TCP_RECV 套接字指令)。
;
; 三個待確認事項 (請機械/電控工程師覆核後移除本段註解):
;   1. 所有 PTEACH 標記的點位皆為佔位值。除 HOME_LEFT 外，其餘點皆
;      表示為 ORIGIN + TRANS(x,y,z,o,a,t) 複合座標 (詳見 INIT_POINTS
;      內註解)，現場只需教 ORIGIN 這一點，其餘偏移量再依
;      CALIBRATION_POINTS.csv 填入即可 (目前仍為「待標定」)。
;   2. I/O 訊號編號 (sig_out_*/sig_in_*) 為佔位值 (輸出 1–2、輸入
;      1001–1002)，對應 SmartCook_信號分配表.docx 中
;      DO_F_1/DO_F_2/DO_R_1/DO_R_2，該文件註明「待你手動補充」，
;      實際腳位需與 F60_R 對接配線後一併確認。
;   3. TCP_LISTEN 的合法埠號範圍是 8192–65535；若展場仍要用 9000，
;      需與電控確認韌體是否放寬此限制，否則需與 PC 端
;      config_connection.py 一併改成落在合法範圍內的埠號。
; =====================================================================

.PROGRAM INIT_CONST()
  ; 手臂識別
  $this_arm = "F60_F"

  ; --- TCP 通訊參數 ---
  port = 9000
  max_length = 255
  tout_accept = 5      ; TCP_ACCEPT 逾時 (秒)，逾時後回到迴圈重新等待
  tout_recv = 10        ; TCP_RECV 逾時 (秒)，PC 端心跳每 3 秒一次
  tout_send = 5

  ; --- I/O 訊號編號 (雙臂對接，佔位值，待電控確認) ---
  ; 依 AS 語言慣例，外部輸出訊號用小號碼，外部輸入訊號從 1001 起算
  ; (參照 AS Language Reference Manual 6.7 節 ON/SIGNAL 可用訊號範圍)。
  sig_out_press_done = 1        ; DO_F_1 (輸出): 壓定完成信號 → F60_R
  sig_out_lift_done = 2         ; DO_F_2 (輸出): 提鏟完成信號 → F60_R
  sig_in_chop_done = 1001       ; DO_R_1 (輸入): 落刀完成信號 ← F60_R
  sig_in_step_done = 1002       ; DO_R_2 (輸入): 步進完成信號 ← F60_R

  ; --- 動作參數 (可依現場試切調整，單位 mm/deg) ---
  appro_mm = 80.0
  chop_down_mm = 40.0
  flip_up_mm = 90.0
  pour_tilt_deg = 90.0

  ; --- 逾時設定 (秒) ---
  timeout_io_sec = 5.0
  timeout_flip_sec = 5.0

  robot_busy = 0
  $rxbuf = ""
.END

; ---------------------------------------------------------------------
; 點位宣告 (PTEACH = 待現場教點，目前為佔位座標)
;
; 除 HOME_LEFT 外，其餘 8 個點皆用複合座標 ORIGIN + TRANS(x,y,z,o,a,t)
; 表示，對應 OBJECT_DEFINITIONS_v1.1.md 的檯面座標系 (左下角為原點)，
; 也對應 CALIBRATION_POINTS.csv 的 X/Y/Angle 欄位。好處: 現場只需教
; ORIGIN 這一點，其餘點皆為相對偏移，ORIGIN 校正後全部自動跟著校正，
; 不必逐點重教。注意: ORIGIN 必須在 F60_F 自己的教示盒上教點——即使
; 是同一個物理檯角，F60_F 與 F60_R 是兩台獨立控制器，各自基座座標系
; 不同，數值不能共用，F60_R 需在自己的教示盒上另外教一次。
; ---------------------------------------------------------------------
.PROGRAM INIT_POINTS()
  POINT ORIGIN = TRANS(0,0,0,0,0,0)   ; PTEACH: 檯面左下角基準點 (F60_F 自身基座座標系)

  ; --- 以下 X,Y,Z,Angle 皆為佔位 0，待 CALIBRATION_POINTS.csv 標定完成後填入 ---
  POINT PICKUP_CUCUMBER = ORIGIN + TRANS(0,0,0,0,0,0)   ; X,Y,Z,Angle ← CSV
  POINT PICKUP_ROMAINE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z,Angle ← CSV
  POINT PICKUP_RED_LEAF = ORIGIN + TRANS(0,0,0,0,0,0)   ; X,Y,Z,Angle ← CSV
  POINT WAIT_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)         ; X,Y,Z ← CSV
  POINT MIX_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)          ; X,Y,Z ← CSV
  POINT WORK_CHOP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z ← CSV
  POINT WORK_FLIP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z ← CSV
  POINT SALAD_BOWL = ORIGIN + TRANS(0,0,0,0,0,0)        ; X,Y,Z ← CSV (ArUco ID 102 輔助標定)
  POINT WASTE_CORNER = ORIGIN + TRANS(0,0,0,0,0,0)      ; X,Y,Z ← CSV

  ; HOME_LEFT 在相機拍不到的高處，與檯面座標系無關，維持獨立絕對點
  POINT HOME_LEFT = TRANS(0,0,0,0,0,0)   ; PTEACH (手工標定，示教盒)
.END

; =====================================================================
; MAIN — 程式進入點 (機器人控制程式)
; =====================================================================
.PROGRAM MAIN()
  CALL INIT_CONST()
  CALL INIT_POINTS()
  SPEED 30 ALWAYS
  ACCURACY 1
  SIGNAL -sig_out_press_done
  SIGNAL -sig_out_lift_done
  LMOVE HOME_LEFT

  CALL OPEN_LISTEN()
  DO
    CALL WAIT_ACCEPT(accepted)
    IF accepted = 1 THEN
      $rxbuf = ""
      CALL DO_HANDSHAKE(hs_ok)
      IF hs_ok = 1 THEN
        conn_lost = 0
        DO
          CALL RECV_LINE($line, rok)
          IF rok = 0 THEN
            conn_lost = 1
          ELSE
            CALL SPLIT_CSV($line)
            CALL DISPATCH()
          END
        UNTIL conn_lost = 1
      END
      TCP_CLOSE cret, sock_id
    END
  UNTIL 1 = 0
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
; 握手: 收到 "connect" 後回覆 "BOARD_ID,F60_CTRL_001"
; ---------------------------------------------------------------------
.PROGRAM DO_HANDSHAKE(.ok)
  CALL RECV_LINE($line, rok)
  IF rok = 0 THEN
    .ok = 0
    RETURN
  END
  IF $line = "connect" THEN
    CALL SEND_LINE("BOARD_ID,F60_CTRL_001")
    .ok = 1
  ELSE
    CALL SEND_LINE("ERROR,E4021")
    .ok = 0
  END
.END

; ---------------------------------------------------------------------
; 讀取一行 CSV 指令 (以 \n 結尾)。.rok=0 代表連線中斷/逾時。
; 內部以 $rxbuf 緩衝跨封包資料，因 TCP_RECV 不保證按行切割。
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
      .rok = 0
      RETURN
    END
    IF recv_n > 0 THEN
      FOR i = 1 TO recv_n
        $rxbuf = $rxbuf + $recv_buf[i]
      END
    END
  UNTIL 1 = 0
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
    IF p = 0 THEN
      $fld[nfld] = $rest
      $rest = ""
    ELSE
      $fld[nfld] = $LEFT($rest, p - 1)
      $rest = $MID($rest, p + 1, LEN($rest) - p)
    END
  UNTIL $rest = "" OR nfld >= 8
.END

; ---------------------------------------------------------------------
; 指令分派
; ---------------------------------------------------------------------
.PROGRAM DISPATCH()
  IF $fld[1] = "HEARTBEAT" THEN
    CALL SEND_LINE("HEARTBEAT_ACK")
    RETURN
  END

  IF robot_busy = 1 THEN
    IF $fld[1] = "STOP" THEN
      CALL DO_STOP()
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
    CALL DO_STOP()
  SVALUE "RESET":
    CALL DO_RESET()
  SVALUE "STATUS":
    CALL DO_STATUS($fld[2])
  SVALUE "READY":
    CALL DO_READY($fld[2])
  ANY :
    CALL SEND_LINE("ERROR,E4021")
  END
.END

; ---------------------------------------------------------------------
; 訊號等待 (含逾時)，.ok=1 收到訊號 / .ok=0 逾時
; ---------------------------------------------------------------------
.PROGRAM WAIT_SIGNAL(sig_no, timeout_sec, .ok)
  TIMER 1 = 0
  WAIT SIG(sig_no) OR TIMER(1) > timeout_sec
  IF SIG(sig_no) THEN
    .ok = 1
  ELSE
    .ok = 0
  END
.END

.PROGRAM WAIT_SIGNAL_OFF(sig_no, timeout_sec, .ok)
  TIMER 1 = 0
  WAIT (SIG(sig_no) == 0) OR TIMER(1) > timeout_sec
  IF SIG(sig_no) == 0 THEN
    .ok = 1
  ELSE
    .ok = 0
  END
.END

; ---------------------------------------------------------------------
; PICKUP,<LOCATION>,<ARM>
; ---------------------------------------------------------------------
.PROGRAM DO_PICKUP(.$location, .$arm)
  IF .$arm <> $this_arm THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END

  found = 1
  IF .$location = "PICKUP_CUCUMBER" THEN
    POINT dest = PICKUP_CUCUMBER
  ELSE
    IF .$location = "PICKUP_ROMAINE" THEN
      POINT dest = PICKUP_ROMAINE
    ELSE
      IF .$location = "PICKUP_RED_LEAF" THEN
        POINT dest = PICKUP_RED_LEAF
      ELSE
        IF .$location = "WAIT_ZONE" THEN
          POINT dest = WAIT_ZONE
        ELSE
          IF .$location = "MIX_ZONE" THEN
            POINT dest = MIX_ZONE
          ELSE
            found = 0
          END
        END
      END
    END
  END

  IF found = 0 THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END

  robot_busy = 1
  SPEED 40 ALWAYS
  LAPPRO dest, appro_mm
  LMOVE dest
  ; TODO: 依實際夾具/鏟取動作插入取料手勢 (鏟子插入角度、聚攏)
  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM>
; 由左鏟(開刃)執行下壓切割，每刀完成後與 F60_R 交握 (壓點步進)
; ---------------------------------------------------------------------
.PROGRAM DO_CHOP(.$food, .cuts, .thick)
  IF .$food <> "CUCUMBER" AND .$food <> "ROMAINE" THEN
    CALL SEND_LINE("ERROR,E4004")
    RETURN
  END
  IF .cuts < 1 OR .cuts > 20 OR .thick <= 0 THEN
    CALL SEND_LINE("ERROR,E4005")
    RETURN
  END

  robot_busy = 1
  SPEED 30 ALWAYS
  LAPPRO WORK_CHOP_ZONE, appro_mm
  LMOVE WORK_CHOP_ZONE

  i = 0
  DO
    DRAW 0, 0, -chop_down_mm            ; 下壓切割
    SIGNAL sig_out_lift_done            ; 通知 F60_R: 本刀已完成 (DO_F_2)
    CALL WAIT_SIGNAL(sig_in_step_done, timeout_io_sec, ok)
    SIGNAL -sig_out_lift_done
    IF ok = 0 THEN
      CALL SEND_LINE("ERROR,E4023")     ; I/O 信號超時 (雙臂握手)
      robot_busy = 0
      RETURN
    END
    DRAW 0, 0, chop_down_mm             ; 提鏟
    DRAW .thick, 0, 0                   ; 步進到下一刀位置
    i = i + 1
  UNTIL i >= .cuts

  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; PLACE,<LOCATION>,<METHOD>
; ---------------------------------------------------------------------
.PROGRAM DO_PLACE(.$location, .$method)
  found = 1
  IF .$location = "SALAD_BOWL" THEN
    POINT dest = SALAD_BOWL
  ELSE
    IF .$location = "WAIT_ZONE" THEN
      POINT dest = WAIT_ZONE
    ELSE
      IF .$location = "MIX_ZONE" THEN
        POINT dest = MIX_ZONE
      ELSE
        IF .$location = "WASTE_CORNER" THEN
          POINT dest = WASTE_CORNER
        ELSE
          found = 0
        END
      END
    END
  END

  IF found = 0 THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END
  IF .$method <> "POUR" AND .$method <> "SCOOP" AND .$method <> "PUSH" THEN
    CALL SEND_LINE("ERROR,E4001")
    RETURN
  END

  robot_busy = 1
  SPEED 40 ALWAYS
  LAPPRO dest, appro_mm
  LMOVE dest

  IF .$method = "POUR" THEN
    SIGNAL sig_out_press_done           ; 通知 F60_R 同步傾倒 (DO_F_1)
    CALL WAIT_SIGNAL(sig_in_chop_done, timeout_io_sec, ok)
    SIGNAL -sig_out_press_done
    TDRAW 0, 0, 0, 0, pour_tilt_deg, 0, 20   ; 鏟子繞刀具 Y 軸傾倒 (角度依治具調整)
    TDRAW 0, 0, 0, 0, -pour_tilt_deg, 0, 20
  ELSE
    IF .$method = "PUSH" THEN
      DRAW 0, 60, 0                     ; 推動廢料至角落 (方向/距離待現場調整)
    END
  END

  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; FLIP,<NUM_CYCLES>,<SPEED_PERCENT> — 左臂為主導方 (先上翻)
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
    DRAW 0, 0, flip_up_mm                ; 左鏟上翻
    SIGNAL sig_out_lift_done             ; 通知 F60_R 本循環開始
    CALL WAIT_SIGNAL(sig_in_step_done, timeout_flip_sec, ok)
    SIGNAL -sig_out_lift_done
    IF ok = 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    DRAW 0, 0, -flip_up_mm
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
  SPEED 20 ALWAYS                        ; 復歸使用較低安全速度
  LMOVE HOME_LEFT
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; STOP — 緊急停止
; ---------------------------------------------------------------------
.PROGRAM DO_STOP()
  BRAKE
  SIGNAL -sig_out_press_done
  SIGNAL -sig_out_lift_done
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; RESET — 清除本程式的應用層狀態，重新準備接受下一個菜色
; 注意: 若控制器已進入系統錯誤(紅燈)，機器人控制程式本身無法自我
; ERESET (ERESET 為 Monitor-only 指令，且 MC 指令明文規定不可用於
; 機器人控制程式，只能在 PC 程式中使用)。真正的系統錯誤重置需由
; 教示盒或另一支獨立 PC 程式 (用 MC ERESET) 處理，此處僅重置本程式
; 的忙碌旗標與交握訊號。
; ---------------------------------------------------------------------
.PROGRAM DO_RESET()
  robot_busy = 0
  SIGNAL -sig_out_press_done
  SIGNAL -sig_out_lift_done
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
  IF robot_busy = 1 THEN
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
  IF robot_busy = 1 THEN
    CALL SEND_LINE("BUSY")
  ELSE
    CALL SEND_LINE("OK")
  END
.END
