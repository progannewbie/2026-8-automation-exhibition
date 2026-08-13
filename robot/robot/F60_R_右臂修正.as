.PROGRAM INIT_CONST()
  $this_arm = "F60_R"

  ; --- TCP 通訊參數 ---
  port = 9000
  max_length = 255
  tout_accept = 5
  tout_recv = 10
  tout_send = 5

  ; --- I/O 訊號編號 (雙臂共用同一組交握訊號，佔位值，待電控確�? ---
  ; �?AS 語言慣例，外部輸出訊號用小號碼，外部輸入訊號�?1001 起算�?  sig_out_step = 1        ; 輸出: 本臂完成目前階段 �?F60_F
  sig_in_step = 1001       ; 輸入: F60_F 完成目前階段 �?F60_F

  ; --- 動作參數 (可依現場試切調整，單�?mm) ---
  appro_mm = 80.0
  press_down_mm = 15.0     ; 壓住食材下壓�?(輕壓，勿過力)
  step_mm = 4.0             ; 壓點隨切割步進距�?(應與 CHOP 厚度一�?
  flip_down_mm = 90.0
  pour_tilt_deg = 90.0
  converge_dx = -20.0      ; PICKUP 集中階段：F60_R 往中心平移�?(�?F60_F 方向相對，待現場確認)
  converge_dy = 0.0

  ; --- 逾時設定 (�? ---
  timeout_io_sec = 5.0
  timeout_flip_sec = 5.0

  robot_busy = 0
  $rxbuf = ""
.END
.PROGRAM INIT_POINTS()
  POINT ORIGIN = TRANS(0,0,0,0,0,0)   ; PTEACH: 檯面左下角基準點 (F60_R 自身基座座標�?

  ; --- 以下 X,Y,Z,Angle 皆為佔位 0，待 CALIBRATION_POINTS.csv 標定完成後填�?---
  POINT PICKUP_CUCUMBER = ORIGIN + TRANS(0,0,0,0,0,0)   ; X,Y,Z,Angle �?CSV
  POINT PICKUP_CARROT = ORIGIN + TRANS(0,0,0,0,0,0)     ; X,Y,Z,Angle �?CSV
  POINT PICKUP_CORN = ORIGIN + TRANS(0,0,0,0,0,0)       ; X,Y,Z,Angle �?CSV
  POINT PRESS_CHOP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)   ; 對應 WORK_CHOP_ZONE 的壓點偏�?  POINT MIX_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)          ; X,Y,Z �?CSV
  POINT WORK_FLIP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z �?CSV
  POINT SALAD_BOWL = ORIGIN + TRANS(0,0,0,0,0,0)        ; X,Y,Z �?CSV (ArUco ID 102 輔助標定)

  ; HOME_RIGHT 在相機拍不到的高處，與檯面座標系無關，維持獨立絕對點
  POINT HOME_RIGHT = TRANS(0,0,0,0,0,0)   ; PTEACH (手工標定，示教盒)

  ; -----------------------------------------------------------------
  ; 翻炒動作點位 (rturn45/90/135)，架構參�?原程�?rs_r.as 裡的
  ; rturn45()/rturn90()/rturn135()。這些點位跟本檔案其他點位使用�?  ; BASE NULL / TOOL RIGHT_SPATULA 不是同一個座標系，是在專屬的
  ; ba_flip (BASE) / ha_flip (TOOL) 底下教的，只能在 DO_FLIP 裡切�?  ; ba_flip/ha_flip 之後才能用，用完要切回來�?  ; 以下皆為佔位值，待現場手動示教�?  ; -----------------------------------------------------------------
  POINT ba_flip = TRANS(0,0,0,0,0,0)   ; PTEACH: 翻炒�?BASE，待手動校點
  POINT ha_flip = TRANS(0,0,0,0,0,0)   ; PTEACH: 翻炒�?TOOL，待手動校點

  POINT rturn45_ready = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn45_down  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn45_turn  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?
  POINT rturn90_ready  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn90_down   = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn90_turn   = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn90_turn10 = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn90_turn20 = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?
  POINT rturn135_ready  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn135_down   = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn135_turn   = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn135_turn10 = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT rturn135_turn20 = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?.END

; ---------------------------------------------------------------------
; 刀具座標設�?(TOOL)，說明同 F60_F_左臂.as�?; ---------------------------------------------------------------------
.END
.PROGRAM INIT_TOOL()
  BASE NULL
  POINT RIGHT_SPATULA = TRANS(0,0,0,0,0,0)   ; PTEACH: 右鏟(平面)相對法蘭面的偏移，待量測/教點
  TOOL RIGHT_SPATULA
.END
.PROGRAM heartput()
  JOINT SPEED9 ACCU1 TIMER0 TOOL1 WORK0 CLAMP1 (OFF,0,0,O) 2 (OFF,0,0,O) OX= WX= #[-30.054,54.056,-92.937,-8.3188,18.918,-169.17]
.END
.PROGRAM MAIN()
  CALL heartput

  CALL INIT_CONST
  CALL INIT_POINTS
  CALL INIT_TOOL
  SPEED 30 ALWAYS
  ACCURACY 1
  SIGNAL -sig_out_step
  LMOVE HOME_RIGHT

  CALL CLEAN_SOCKET
  CALL OPEN_LISTEN
  DO
    CALL WAIT_ACCEPT(accepted)
    IF accepted == 1 THEN
      sock_open_flag = 1
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
      CALL DISCONNECT
    END
  UNTIL 1 == 0
.END
.PROGRAM DISCONNECT()
  TCP_CLOSE cret, sock_id
  sock_open_flag = 0
.END
.PROGRAM CLEAN_SOCKET()
  IF sock_open_flag == 1 THEN
    PRINT "偵測到上次殘留的連線 sock_id=", sock_id, "，先關閉再繼�?"
    CALL DISCONNECT
  END
  TCP_END_LISTEN eret, port
  IF eret < 0 THEN
    PRINT "TCP_END_LISTEN 啟動清理 回傳=", eret, "（本來就沒有殘留監聽，正常現象）"
  ELSE
    PRINT "TCP_END_LISTEN 啟動清理 成功，已釋放上次殘留的監聽狀�?"
  END
.END
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
.PROGRAM WAIT_ACCEPT(.accepted)
  TCP_ACCEPT sock_id, port, tout_accept, client_ip[1]
  IF sock_id < 0 THEN
    .accepted = 0
  ELSE
    PRINT "TCP_ACCEPT OK id=", sock_id
    .accepted = 1
  END
.END
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
.PROGRAM SEND_LINE(.$msg)
  $send_buf[1] = .$msg + $CHR(10)
  TCP_SEND sret, sock_id, $send_buf[1], 1, tout_send
.END
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
.PROGRAM DO_PICKUP(.$location, .$arm)
  IF .$arm <> "F60_F" THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END

  found = 1
  IF .$location == "PICKUP_CUCUMBER" THEN
    POINT target_pt = PICKUP_CUCUMBER
  ELSE
    IF .$location == "PICKUP_CARROT" THEN
      POINT target_pt = PICKUP_CARROT
    ELSE
      IF .$location == "PICKUP_CORN" THEN
        POINT target_pt = PICKUP_CORN
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

  ; 階段 3: 集中 (方向�?F60_F 相對，佔位示意，待現場調�?
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
    CALL SYNC_STEP(ok)                  ; �?F60_F 完成本刀下壓
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    DRAW 0, 0, -press_down_mm           ; 壓住食材
    DRAW step_mm, 0, 0                  ; 隨切割步�?(應與 CHOP 厚度一�?
    DRAW 0, 0, press_down_mm            ; 鬆開，準備下一刀
    i = i + 1
  UNTIL i >= .cuts

  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
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
    CALL SEND_LINE ("ERROR,E4002")
    RETURN
  END
  IF .$method <> "POUR" AND .$method <> "SCOOP" AND .$method <> "PUSH" THEN
    CALL SEND_LINE ("ERROR,E4001")
    RETURN
  END
  
  robot_busy = 1
  SPEED 40 ALWAYS
  LAPPRO target_pt, appro_mm
  LMOVE target_pt
  
  IF .$method == "POUR" THEN
    CALL SYNC_STEP (ok)                  ; �?F60_F 會合，一起傾�?
    IF ok == 0 THEN
      CALL SEND_LINE ("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    TDRAW 0, 0, 0, 0, pour_tilt_deg, 0, 20      ; 雙鏟對合傾倒手�?(角度依治具調�?
    TDRAW 0, 0, 0, 0, -pour_tilt_deg, 0, 20
  END
  
  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE ("OK")
.END
.PROGRAM DO_RTURN45(.ok)
  LMOVE rturn45_ready
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn45_down
  LMOVE rturn45_turn
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn45_down
  LMOVE rturn45_ready
  CALL SYNC_STEP(s)
  .ok = s
.END
.PROGRAM DO_RTURN90(.ok)
  LMOVE rturn90_ready
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn90_down
  LMOVE rturn90_turn
  LMOVE rturn90_turn10
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn90_turn20
  LMOVE rturn90_ready
  CALL SYNC_STEP(s)
  .ok = s
.END
.PROGRAM DO_RTURN135(.ok)
  LMOVE rturn135_ready
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn135_down
  LMOVE rturn135_turn
  LMOVE rturn135_turn10
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn135_turn20
  LMOVE rturn135_ready
  CALL SYNC_STEP(s)
  .ok = s
.END
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
  BASE ba_flip
  TOOL ha_flip

  i = 0
  DO
    ; 階段 1�?0°/90° 配對
    CALL DO_RTURN90(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE NULL
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 2�?35°/45° 配對 (本臂 45°)
    CALL DO_RTURN45(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE NULL
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 3�?5°/135° 配對 (本臂 135°)
    CALL DO_RTURN135(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE NULL
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    i = i + 1
  UNTIL i >= .cycles

  BASE NULL
  TOOL RIGHT_SPATULA
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
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
.PROGRAM DO_STOP()
  BRAKE
  SIGNAL -sig_out_step
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
.PROGRAM DO_RESET()
  robot_busy = 0
  SIGNAL -sig_out_step
  CALL SEND_LINE("OK")
.END
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
.PROGRAM Comment___ () ; Comments for IDE. Do not use.
	; @@@ PROJECT @@@
	; @@@ PROJECTNAME @@@
	; F60_R_�ұ�����
	; @@@ HISTORY @@@
	; @@@ INSPECTION @@@
	; @@@ CONNECTION @@@
	; Rs07_R
	; 192.168.5.7
	; 23
	; @@@ PROGRAM @@@
	; 0:INIT_CONST:F
	; 0:INIT_POINTS:F
	; 0:INIT_TOOL:F
	; 0:heartput:F
	; 0:MAIN:F
	; 0:DISCONNECT:F
	; 0:CLEAN_SOCKET:F
	; 0:OPEN_LISTEN:F
	; 0:WAIT_ACCEPT:F
	; 0:DO_HANDSHAKE:F
	; 0:RECV_LINE:F
	; 0:SEND_LINE:F
	; 0:SPLIT_CSV:F
	; 0:DISPATCH:F
	; 0:WAIT_SIGNAL:F
	; 0:WAIT_SIGNAL_OFF:F
	; 0:SYNC_STEP:F
	; 0:DO_PICKUP:F
	; 0:DO_CHOP:F
	; 0:DO_PLACE:F
	; 0:DO_RTURN45:F
	; 0:DO_RTURN90:F
	; 0:DO_RTURN135:F
	; 0:DO_FLIP:F
	; 0:DO_HOME:F
	; 0:DO_STOP:F
	; 0:DO_RESET:F
	; 0:DO_STATUS:F
	; 0:DO_READY:F
	; @@@ TRANS @@@
	; @@@ JOINTS @@@
	; @@@ REALS @@@
	; @@@ STRINGS @@@
	; @@@ INTEGER @@@
	; @@@ SIGNALS @@@
	; @@@ TOOLS @@@
	; @@@ BASE @@@
	; @@@ FRAME @@@
	; @@@ BOOL @@@
	; @@@ DEFAULTS @@@
	; BASE: NULL
	; TOOL: NULL
.END
