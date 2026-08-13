.PROGRAM INIT_CONST()
  ; 手臂識別
  $this_arm = "F60_F"

  ; --- TCP 通訊參數 ---
  port = 9000
  max_length = 255
  tout_accept = 5      ; TCP_ACCEPT 逾時 (�?，逾時後回到迴圈重新等�?  tout_recv = 10        ; TCP_RECV 逾時 (�?，PC 端心跳每 3 秒一�?  tout_send = 5

  ; --- I/O 訊號編號 (雙臂共用同一組交握訊號，佔位值，待電控確�? ---
  ; �?AS 語言慣例，外部輸出訊號用小號碼，外部輸入訊號�?1001 起算
  ; (參照 AS Language Reference Manual 6.7 節 ON/SIGNAL 可用訊號範圍)�?  sig_out_step = 1        ; 輸出: 本臂完成目前階段 �?F60_R
  sig_in_step = 1001       ; 輸入: F60_R 完成目前階段 �?F60_R

  ; --- 動作參數 (可依現場試切調整，單�?mm/deg) ---
  appro_mm = 80.0
  chop_down_mm = 40.0
  flip_up_mm = 90.0
  pour_tilt_deg = 90.0
  converge_dx = 20.0      ; PICKUP 集中階段：F60_F 往中心平移�?(方向待現場確�?
  converge_dy = 0.0

  ; --- 逾時設定 (�? ---
  timeout_io_sec = 5.0
  timeout_flip_sec = 5.0

  robot_busy = 0
  $rxbuf = ""
.END
.PROGRAM INIT_POINTS()
  POINT ORIGIN = TRANS(0,0,0,0,0,0)   ; PTEACH: 檯面左下角基準點 (F60_F 自身基座座標�?

  ; --- 以下 X,Y,Z,Angle 皆為佔位 0，待 CALIBRATION_POINTS.csv 標定完成後填�?---
  POINT PICKUP_CUCUMBER = ORIGIN + TRANS(0,0,0,0,0,0)   ; X,Y,Z,Angle �?CSV
  POINT PICKUP_CARROT = ORIGIN + TRANS(0,0,0,0,0,0)     ; X,Y,Z,Angle �?CSV
  POINT PICKUP_CORN = ORIGIN + TRANS(0,0,0,0,0,0)       ; X,Y,Z,Angle �?CSV
  POINT WAIT_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)         ; X,Y,Z �?CSV
  POINT MIX_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)          ; X,Y,Z �?CSV
  POINT WORK_CHOP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z �?CSV
  POINT WORK_FLIP_ZONE = ORIGIN + TRANS(0,0,0,0,0,0)    ; X,Y,Z �?CSV
  POINT SALAD_BOWL = ORIGIN + TRANS(0,0,0,0,0,0)        ; X,Y,Z �?CSV (ArUco ID 102 輔助標定)
  POINT WASTE_CORNER = ORIGIN + TRANS(0,0,0,0,0,0)      ; X,Y,Z �?CSV

  ; HOME_LEFT 在相機拍不到的高處，與檯面座標系無關，維持獨立絕對點
  POINT HOME_LEFT = TRANS(0,0,0,0,0,0)   ; PTEACH (手工標定，示教盒)

  ; -----------------------------------------------------------------
  ; 翻炒動作點位 (lturn45/90/135)，架構參�?原程�?rs_f.as 裡的
  ; lturn45()/lturn90()/lturn135()。這些點位跟本檔案其他點位使用�?  ; BASE NULL / TOOL LEFT_SPATULA 不是同一個座標系，是在專屬的
  ; ba_flip (BASE) / ha_flip (TOOL) 底下教的，只能在 DO_FLIP 裡切�?  ; ba_flip/ha_flip 之後才能用，用完要切回來�?  ; 以下皆為佔位值，待現場手動示教�?  ; -----------------------------------------------------------------
  POINT ba_flip = TRANS(0,0,0,0,0,0)   ; PTEACH: 翻炒�?BASE，待手動校點
  POINT ha_flip = TRANS(0,0,0,0,0,0)   ; PTEACH: 翻炒�?TOOL，待手動校點

  POINT lturn45_ready = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn45_down  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn45_turn  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?
  POINT lturn90_ready = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn90_down  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn90_turn  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?
  POINT lturn135_ready  = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn135_down   = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn135_turn   = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn135_turn10 = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?  POINT lturn135_turn20 = TRANS(0,0,0,0,0,0)   ; PTEACH: 待手動校�?.END

; ---------------------------------------------------------------------
; 刀具座標設�?(TOOL)。真實產線程式一律會先設�?BASE/TOOL 才開始動作，
; 這裡先前遺漏了——沒設定 TOOL 時，DRAW/TDRAW 會用預設的法蘭面座標�?; 計算，跟鏟子實際末端偏移對不上，尤其影響 TDRAW 的傾倒手勢�?; ---------------------------------------------------------------------
.END
.PROGRAM INIT_TOOL()
  BASE NULL
  POINT LEFT_SPATULA = TRANS(0,0,0,0,0,0)   ; PTEACH: 左鏟(開刃)相對法蘭面的偏移，待量測/教點
  TOOL LEFT_SPATULA
.END
.PROGRAM heartput()
  JOINT SPEED9 ACCU1 TIMER0 TOOL1 WORK0 CLAMP1 (OFF,0,0,O) 2 (OFF,0,0,O) OX= WX= #[125.8,-36.683,104.25,-26.709,-9.052,30.916]
.END
.PROGRAM MAIN()
  CALL heartput

  CALL INIT_CONST
  CALL INIT_POINTS
  CALL INIT_TOOL
  SPEED 30 ALWAYS
  ACCURACY 1
  SIGNAL -sig_out_step
  LMOVE HOME_LEFT

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
    CALL SEND_LINE("BOARD_ID,F60_CTRL_001")
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
        IF .$location == "WAIT_ZONE" THEN
          POINT target_pt = WAIT_ZONE
        ELSE
          IF .$location == "MIX_ZONE" THEN
            POINT target_pt = MIX_ZONE
          ELSE
            found = 0
          END
        END
      END
    END
  END

  IF found == 0 THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END

  robot_busy = 1
  SPEED 40 ALWAYS

  ; 階段 1: 就緒 �?兩臂各自到位到取料點正上�?  LAPPRO target_pt, appro_mm
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    robot_busy = 0
    RETURN
  END

  ; 階段 2: 下降 �?一起下降到取料高度
  LMOVE target_pt
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    robot_busy = 0
    RETURN
  END

  ; 階段 3: 集中 �?往中間收攏 (方向/距離為佔位示意，待現場調�?
  DRAW converge_dx, converge_dy, 0
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    robot_busy = 0
    RETURN
  END

  ; 階段 4: 抬起 �?一起抬起離開取料區
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
  IF .$food <> "CUCUMBER" AND .$food <> "CARROT" AND .$food <> "CORN" THEN
    CALL SEND_LINE ("ERROR,E4004")
    RETURN
  END
  IF .cuts < 1 OR .cuts > 20 OR .thick <= 0 THEN
    CALL SEND_LINE ("ERROR,E4005")
    RETURN
  END
  
  robot_busy = 1
  SPEED 30 ALWAYS
  LAPPRO WORK_CHOP_ZONE, appro_mm
  LMOVE WORK_CHOP_ZONE
  
  i = 0
  DO
    DRAW 0, 0, -chop_down_mm            ; 下壓切割
    CALL SYNC_STEP (ok)                  ; 通知/等待 F60_R 完成本刀壓料步�?
    IF ok == 0 THEN
      CALL SEND_LINE ("ERROR,E4023")     ; I/O 信號超時 (雙臂握手)
      robot_busy = 0
      RETURN
    END
    DRAW 0, 0, chop_down_mm             ; 提鏟
    DRAW .thick, 0, 0                   ; 步進到下一刀位置
    i = i + 1
  UNTIL i >= .cuts
  
  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE ("OK")
.END
.PROGRAM DO_PLACE(.$location, .$method)
  found = 1
  IF .$location == "SALAD_BOWL" THEN
    POINT target_pt = SALAD_BOWL
  ELSE
    IF .$location == "WAIT_ZONE" THEN
      POINT target_pt = WAIT_ZONE
    ELSE
      IF .$location == "MIX_ZONE" THEN
        POINT target_pt = MIX_ZONE
      ELSE
        IF .$location == "WASTE_CORNER" THEN
          POINT target_pt = WASTE_CORNER
        ELSE
          found = 0
        END
      END
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
    CALL SYNC_STEP (ok)                  ; �?F60_R 會合，一起傾�?
    IF ok == 0 THEN
      CALL SEND_LINE ("ERROR,E4023")
      robot_busy = 0
      RETURN
    END
    TDRAW 0, 0, 0, 0, pour_tilt_deg, 0, 20   ; 鏟子繞刀�?Y 軸傾�?(角度依治具調�?
    TDRAW 0, 0, 0, 0, -pour_tilt_deg, 0, 20
  ELSE
    IF .$method == "PUSH" THEN
      DRAW 0, 60, 0                     ; 推動廢料至角�?(方向/距離待現場調�?
    END
  END
  
  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE ("OK")
.END
.PROGRAM DO_LTURN45(.ok)
  LMOVE lturn45_ready
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE lturn45_down
  LMOVE lturn45_turn
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE lturn45_down
  LMOVE lturn45_ready
  CALL SYNC_STEP(s)
  .ok = s
.END
.PROGRAM DO_LTURN90(.ok)
  LMOVE lturn90_ready
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE lturn90_down
  LMOVE lturn90_turn
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE lturn90_down
  LMOVE lturn90_ready
  CALL SYNC_STEP(s)
  .ok = s
.END
.PROGRAM DO_LTURN135(.ok)
  LMOVE lturn135_ready
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE lturn135_down
  LMOVE lturn135_turn
  LMOVE lturn135_turn10
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE lturn135_turn20
  LMOVE lturn135_ready
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
    CALL DO_LTURN90(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE NULL
      TOOL LEFT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 2�?35°/45° 配對 (本臂 135°)
    CALL DO_LTURN135(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE NULL
      TOOL LEFT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 3�?5°/135° 配對 (本臂 45°)
    CALL DO_LTURN45(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE NULL
      TOOL LEFT_SPATULA
      robot_busy = 0
      RETURN
    END

    i = i + 1
  UNTIL i >= .cycles

  BASE NULL
  TOOL LEFT_SPATULA
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
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
	; F60_F_�������
	; @@@ HISTORY @@@
	; 31.07.2026 17:36:13
	; 
	; @@@ INSPECTION @@@
	; @@@ CONNECTION @@@
	; Rs07_F
	; 192.168.5.2
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
	; 0:DO_LTURN45:F
	; 0:DO_LTURN90:F
	; 0:DO_LTURN135:F
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
