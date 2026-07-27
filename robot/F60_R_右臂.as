; =====================================================================
; SmartCook 機械手臂控制程式 — F60_R (右臂 / 輔助固定臂)
; 語言: Kawasaki AS Language (F 控制器)
; 版本: v0.2 (骨架 skeleton)
; 對應規格書: COMMAND_SPECIFICATION.md / CONNECTION_PROTOCOL.md /
;             OBJECT_DEFINITIONS_v1.1.md / SmartCook_信號分配表.docx
;
; 請與 F60_F_左臂.as 對照閱讀，兩者共用同一組雙臂對接 I/O 訊號。
; 通訊/教點待確認事項同 F60_F_左臂.as 開頭說明，此處不重複。
;
; 架構說明:
;   MAIN                  — 處理 PC 端 TCP/CSV 指令 (HOME/STOP/RESET/
;                           STATUS/READY/FLIP/PLACE，必要時 PICKUP)。
;   DO_ASSIST_PRESS_STEP  — 用 ON...CALL 中斷機制監聽 F60_F 的
;   DO_ASSIST_POUR          I/O 交握信號，在 R 臂閒置等待 PC 指令期間
;                           (阻塞於 RECV_LINE) 也能即時完成「壓料/
;                           隨刀步進/協同傾倒」等動作。這是 AS 語言
;                           官方支援的非同步中斷寫法 (Reference Manual
;                           6.7 節 ON/ONI 指令)，不是背景併發任務；
;                           每次中斷觸發後，處理常式結尾都會重新執行
;                           一次 ON 以重新武裝下一次邊緣觸發 (手冊
;                           6.7 節註記: 中斷一旦觸發即取消監聽)。
; =====================================================================

.PROGRAM INIT_CONST()
  $this_arm = "F60_R"

  ; --- TCP 通訊參數 ---
  port = 9000
  max_length = 255
  tout_accept = 5
  tout_recv = 10
  tout_send = 5

  ; --- I/O 訊號編號 (與 F60_F 對接，佔位值，待電控確認) ---
  ; 依 AS 語言慣例，外部輸出訊號用小號碼，外部輸入訊號從 1001 起算。
  sig_out_chop_done = 1        ; DO_R_1 (輸出): 落刀完成信號 → F60_F
  sig_out_step_done = 2        ; DO_R_2 (輸出): 步進完成信號 → F60_F
  sig_in_press_done = 1001     ; DO_F_1 (輸入): 壓定完成信號 ← F60_F
  sig_in_lift_done = 1002      ; DO_F_2 (輸入): 提鏟完成信號 ← F60_F

  ; --- 動作參數 (可依現場試切調整，單位 mm) ---
  appro_mm = 80.0
  press_down_mm = 15.0     ; 壓住食材下壓量 (輕壓，勿過力)
  step_mm = 4.0             ; 壓點隨切割步進距離 (應與 CHOP 厚度一致)
  flip_down_mm = 90.0
  pour_tilt_deg = 90.0

  ; --- 逾時設定 (秒) ---
  timeout_io_sec = 5.0
  timeout_flip_sec = 5.0

  robot_busy = 0
  $rxbuf = ""
.END

; ---------------------------------------------------------------------
; 點位宣告 (PTEACH = 待現場教點，目前為佔位座標)
; ---------------------------------------------------------------------
.PROGRAM INIT_POINTS()
  POINT PRESS_CHOP_ZONE = TRANS(0,0,0,0,0,0)   ; PTEACH: WORK_CHOP_ZONE 對應壓點
  POINT MIX_ZONE = TRANS(0,0,0,0,0,0)          ; PTEACH
  POINT WORK_FLIP_ZONE = TRANS(0,0,0,0,0,0)    ; PTEACH
  POINT SALAD_BOWL = TRANS(0,0,0,0,0,0)        ; PTEACH (ArUco ID 102 輔助標定)
  POINT PICKUP_RED_LEAF = TRANS(0,0,0,0,0,0)   ; PTEACH (雙鏟協作聚攏)
  POINT HOME_RIGHT = TRANS(0,0,0,0,0,0)        ; PTEACH (手工標定，示教盒)
.END

; =====================================================================
; MAIN — 程式進入點 (PC 指令通道 + 雙臂中斷監聽)
; =====================================================================
.PROGRAM MAIN()
  CALL INIT_CONST()
  CALL INIT_POINTS()
  SPEED 30 ALWAYS
  ACCURACY 1
  SIGNAL -sig_out_chop_done
  SIGNAL -sig_out_step_done
  LMOVE HOME_RIGHT

  ; 武裝雙臂交握中斷: 不論 PC 端目前有沒有下指令，只要 F60_F 拉高
  ; 這兩個訊號，就會中斷目前流程並執行對應的輔助動作。
  ON sig_in_lift_done CALL DO_ASSIST_PRESS_STEP, 5
  ON sig_in_press_done CALL DO_ASSIST_POUR, 5

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
; 每刀壓點下壓 + 步進，回報 F60_F 可提鏟繼續下一刀
; 中斷觸發: sig_in_lift_done 由 OFF→ON (F60_F 完成本刀下壓後拉高)
; ---------------------------------------------------------------------
.PROGRAM DO_ASSIST_PRESS_STEP()
  robot_busy = 1
  LMOVE PRESS_CHOP_ZONE
  DRAW 0, 0, -press_down_mm
  DRAW step_mm, 0, 0
  SIGNAL sig_out_step_done               ; DO_R_2: 步進完成 → F60_F
  CALL WAIT_SIGNAL_OFF(sig_in_lift_done, timeout_io_sec, ok)
  SIGNAL -sig_out_step_done
  robot_busy = 0
  ON sig_in_lift_done CALL DO_ASSIST_PRESS_STEP, 5   ; 重新武裝，監聽下一刀
.END

; ---------------------------------------------------------------------
; 沙拉盤裝盤：右鏟托底配合左鏟傾倒
; 中斷觸發: sig_in_press_done 由 OFF→ON (F60_F 就位待傾倒後拉高)
; ---------------------------------------------------------------------
.PROGRAM DO_ASSIST_POUR()
  robot_busy = 1
  LMOVE SALAD_BOWL
  TDRAW 0, 0, 0, 0, pour_tilt_deg, 0, 20      ; 雙鏟對合傾倒手勢 (角度依治具調整)
  SIGNAL sig_out_chop_done               ; DO_R_1: 就位完成 → F60_F
  CALL WAIT_SIGNAL_OFF(sig_in_press_done, timeout_io_sec, ok)
  SIGNAL -sig_out_chop_done
  TDRAW 0, 0, 0, 0, -pour_tilt_deg, 0, 20
  robot_busy = 0
  ON sig_in_press_done CALL DO_ASSIST_POUR, 5        ; 重新武裝，監聽下一次裝盤
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
  IF rok = 0 THEN
    .ok = 0
    RETURN
  END
  IF $line = "connect" THEN
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
  SVALUE "CHOP":
    CALL SEND_LINE("ERROR,E4021")      ; CHOP 一律送左臂，右臂不支援
  ANY :
    CALL SEND_LINE("ERROR,E4021")
  END
.END

; ---------------------------------------------------------------------
; 訊號等待 (含逾時)，.ok=1 成功 / .ok=0 逾時
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
; PICKUP,<LOCATION>,<ARM> — 主要用於紅捲鬚雙鏟協作聚攏
; ---------------------------------------------------------------------
.PROGRAM DO_PICKUP(.$location, .$arm)
  IF .$arm <> $this_arm THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END
  IF .$location <> "PICKUP_RED_LEAF" THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END

  robot_busy = 1
  SPEED 40 ALWAYS
  LAPPRO PICKUP_RED_LEAF, appro_mm
  LMOVE PICKUP_RED_LEAF
  ; TODO: 低角度切入葉團底部，與左鏟對合成托 (雙鏟協作)
  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END

; ---------------------------------------------------------------------
; PLACE,<LOCATION>,<METHOD> — 主要用於中間位置托運 (SCOOP)
; ---------------------------------------------------------------------
.PROGRAM DO_PLACE(.$location, .$method)
  found = 1
  IF .$location = "MIX_ZONE" THEN
    POINT dest = MIX_ZONE
  ELSE
    IF .$location = "SALAD_BOWL" THEN
      POINT dest = SALAD_BOWL
    ELSE
      found = 0
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
    CALL WAIT_SIGNAL(sig_in_lift_done, timeout_flip_sec, ok)   ; 等左鏟上翻開始
    IF ok = 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    DRAW 0, 0, -flip_down_mm             ; 右鏟下壓並翻
    SIGNAL sig_out_step_done             ; 通知左鏟本循環完成
    DRAW 0, 0, flip_down_mm
    CALL WAIT_SIGNAL_OFF(sig_in_lift_done, timeout_flip_sec, ok)
    SIGNAL -sig_out_step_done
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
  SIGNAL -sig_out_chop_done
  SIGNAL -sig_out_step_done
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
  SIGNAL -sig_out_chop_done
  SIGNAL -sig_out_step_done
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
