.PROGRAM INIT_SWITCHES()
  CP ON                    ; 連續軌跡制御動作 有效 — LMOVE/DRAW 連續動作(切割、翻炒)平滑銜接需要
  CHECK.HOLD OFF           ; 暫停狀態下小鍵盤啟動 無效
  CYCLE.STOP OFF           ; 外部暫停時自動運轉停止 無效
  MESSAGES ON              ; 訊息輸出 有效 — 本程式大量用 PRINT 除錯訊息，需要開啟才看得到
  OX.PREOUT ON             ; OX信號輸出時機 動作開始時
  PREFETCH.SIGINS OFF      ; AS輸出入信號先讀取 禁止
  QTOOL OFF                ; 教導時TOOL資料先自動切換 無效 — 本程式有 RIGHT_SPATULA/ha_flip 兩組 TOOL，教點時避免自動切換造成教到錯的座標系
  RPS ON                   ; 外部程式選擇 有效
  SCREEN ON                ; 畫面表示制御一時停止 有效
  REP_ONCE OFF             ; REPEAT回數 連續
  STP_ONCE OFF             ; STEP實行 連續
  AUTOSTART.PC ON          ; 控制電源ON時PC1自動開始 — 展場斷電重開後自動執行 MAIN，不需人工按 EXECUTE
  AUTOSTART2.PC ON         ; 控制電源ON時PC2自動開始
  AUTOSTART3.PC OFF        ; 控制電源ON時PC3自動開始
  AUTOSTART4.PC OFF        ; 控制電源ON時PC4自動開始
  AUTOSTART5.PC OFF        ; 控制電源ON時PC5自動開始
  ERRSTART.PC OFF          ; ERROR時PC開始 無效
  DISPIO_01 OFF            ; IO表示方式 O,X
  ABS.SPEED ON             ; 絕對速度動作 有效 — 不受各控制器 monitor speed 旋鈕影響，雙臂真正等速
  SLOW_START OFF           ; 低速START機能 無效
  AFTER.WAIT.TMR OFF       ; 簡易WX開始Timing 軸一致後
.END
.PROGRAM INIT_CONST()
  $this_arm = "F60_R"

  ; --- TCP 通訊參數 ---
  port = 9000
  max_length = 255
  tout_accept = 5
  tout_recv = 10
  tout_send = 5

  ; --- I/O 訊號編號 (雙臂共用同一組交握訊號，電控已確認為最終配線值) ---
  ; 依 AS 語言慣例，外部輸出訊號用小號碼，外部輸入訊號從 1001 起算。
  sig_out_step = 1        ; 輸出: 本臂完成目前階段 → F60_F
  sig_in_step = 1001       ; 輸入: F60_F 完成目前階段 ← F60_F

  ; --- 動作參數 (可依現場試切調整，單位 mm) ---
  appro_mm = 50.0
  press_down_mm = 15.0     ; 壓住食材下壓量 (輕壓，勿過力)
  flip_down_mm = 90.0
  pour_tilt_deg = 90.0
  converge_dx = 0.0      ; PICKUP 集中階段：F60_R 往中心平移量 (現場試出的值)
  converge_dy = -30.0
  chop_spread_dx = 0.0    ; PICKUP 階段 5 散開階段：F60_R 往外平移量 (★ 佔位值，待現場測試)
  chop_spread_dy = 30.0

  ; --- 逾時設定 (秒) ---
  timeout_io_sec = 30.0
  timeout_flip = 30.0

  robot_busy = 0
  $rxbuf = ""
.END
.PROGRAM INIT_POINTS() #0
  POINT origin = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 檯面左下角基準點 (須在 BASE ba 生效後教點，見 INIT_TOOL)
  POINT pickup_origin = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 取料區專用基準點，供 DO_PICKUP 視覺座標換算用，待手動校點
  ; --- 以下 X,Y,Z,Angle 皆為佔位 0，待 CALIBRATION_POINTS.csv 標定完成後填入 ---
  POINT pickup_cucumber = origin + TRANS (0, 0, 0, 0, 0, 0)   ; X,Y,Z,Angle ← CSV
  POINT pickup_carrot = origin + TRANS (0, 0, 0, 0, 0, 0)     ; X,Y,Z,Angle ← CSV
  POINT pickup_romaine = origin + TRANS (0, 0, 0, 0, 0, 0)       ; X,Y,Z,Angle ← CSV
  POINT press_chop_zone = origin + TRANS (0, 0, 0, 0, 0, 0)   ; 對應 WORK_CHOP_ZONE 的壓點偏移
  POINT mix_zone = origin + TRANS (0, 0, 0, 0, 0, 0)          ; X,Y,Z ← CSV
  POINT work_flip_zone = origin + TRANS (0, 0, 0, 0, 0, 0)    ; X,Y,Z ← CSV
  POINT salad_bowl = origin + TRANS (0, 0, 0, 0, 0, 0)        ; X,Y,Z ← CSV (ArUco ID 102 輔助標定)
  ; HOME_RIGHT 在相機拍不到的高處，與檯面座標系無關，維持獨立絕對點
  ; ★ 目前為零值佔位：MAIN() 開機第一件事就是 LMOVE HOME_RIGHT，
  ; 在現場用示教盒實際教點覆蓋前，執行到這裡會是未驗證的位置，勿通電後直接 EXECUTE
  POINT home_right = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH (手工標定，示教盒)
  ; -----------------------------------------------------------------
  ; 翻炒動作點位 (rturn45/90/135)，架構參考 原程式/rs_r.as 裡的
  ; rturn45()/rturn90()/rturn135()。這些點位跟本檔案其他點位使用的
  ; BASE ba / TOOL RIGHT_SPATULA 不是同一個座標系，是在專屬的
  ; ba_flip (BASE) / ha_flip (TOOL) 底下教的，只能在 DO_FLIP 裡切到
  ; ba_flip/ha_flip 之後才能用，用完要切回來。
  ; 以下皆為佔位值，待現場手動示教。
  ; -----------------------------------------------------------------
  ;POINT ba_flip = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 翻炒用 BASE，待手動校點
  ;POINT ha_flip = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 翻炒用 TOOL，待手動校點
  ;POINT rturn45_ready = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn45_down = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn45_turn = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn90_ready = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn90_down = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn90_turn = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn135_ready = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn135_down = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn135_turn = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn135_turn10 = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
  ;POINT rturn135_turn20 = TRANS (0, 0, 0, 0, 0, 0)   ; PTEACH: 待手動校點
.END
.PROGRAM INIT_TOOL()
  BASE NULL
  POINT ba = TRANS(43, 0, 0, 0, -90, 0)                      ; 基礎座標 (原程式 rs_r.as init1222())
  BASE ba
  POINT RIGHT_SPATULA = TRANS(-50, -230, 50, 90, 40, -90)    ; 右鏟工具座標 (原程式 rs_r.as init1222()，沿用同一支鏟具)
  TOOL RIGHT_SPATULA
  POINT ha_pickup = TRANS(-50, -320, 50, -90, 38, 90)   ; PICKUP/PLACE 專用鏟具姿勢 (現場已教點)
.END
.PROGRAM heartput()
  JOINT SPEED9 ACCU1 TIMER0 TOOL1 WORK0 CLAMP1 (OFF,0,0,O) 2 (OFF,0,0,O) OX= WX= #[-30.054,54.056,-92.937,-8.3188,18.918,-169.17]
.END
.PROGRAM MAIN()
  CALL heartput

  CALL INIT_SWITCHES
  CALL INIT_CONST
  ;CALL INIT_POINTS     ; 點位已現場教過，不重跑避免蓋回佔位值 0
  CALL INIT_TOOL
  SPEED 50 MM/S ALWAYS   ; ★ 絕對速度，待現場測試調整
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
    PRINT "偵測到上次殘留的連線 sock_id=", sock_id, "，先關閉再繼續"
    CALL DISCONNECT
  END
  TCP_END_LISTEN eret, port
  IF eret < 0 THEN
    PRINT "TCP_END_LISTEN 啟動清理 回傳=", eret, "（本來就沒有殘留監聽，正常現象）"
  ELSE
    PRINT "TCP_END_LISTEN 啟動清理 成功，已釋放上次殘留的監聽狀態"
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
    CALL DO_PICKUP($fld[2], $fld[3], VAL($fld[4]), VAL($fld[5]), VAL($fld[6]))
  SVALUE "CHOP":
    CALL DO_CHOP($fld[2], VAL($fld[3]), VAL($fld[4]))
  SVALUE "PLACE":
    CALL DO_PLACE($fld[2], $fld[3], $fld[4])
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
  SVALUE "IOTEST":
    CALL DO_IOTEST($fld[2])
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
.PROGRAM DO_IOTEST(.$op)
  ; 純 I/O 接線測試，跳過 SYNC_STEP/動作流程，直接操作/讀取訊號腳位
  IF .$op == "ON" THEN
    SIGNAL sig_out_step
    CALL SEND_LINE("OK")
  ELSE
    IF .$op == "OFF" THEN
      SIGNAL -sig_out_step
      CALL SEND_LINE("OK")
    ELSE
      IF .$op == "READ" THEN
        IF SIG(sig_in_step) THEN
          CALL SEND_LINE("SIG,1")
        ELSE
          CALL SEND_LINE("SIG,0")
        END
      ELSE
        CALL SEND_LINE("ERROR,E4001")
      END
    END
  END
.END
.PROGRAM SYNC_STEP(.ok)
  SIGNAL sig_out_step
  CALL WAIT_SIGNAL(sig_in_step, timeout_io_sec, ok1)
  SIGNAL -sig_out_step
  .ok = ok1
.END
; .x_mm/.y_mm/.angle_deg：PC 端 YOLO+手眼標定即時算出的食材座標
.PROGRAM DO_PICKUP(.$location, .$arm, .x_mm, .y_mm, .angle_deg)
  IF .$arm <> "F60_F" THEN
    CALL SEND_LINE("ERROR,E4003")
    RETURN
  END

  ; WAIT_ZONE 已移除：暫存區的搬運改由 DO_PLACE 的來源參數處理，不再需要先 PICKUP 取回。
  found = 1
  IF .$location == "PICKUP_CUCUMBER" OR .$location == "PICKUP_CARROT" OR .$location == "PICKUP_ROMAINE" THEN
    POINT target_pt = TRANS(.x_mm, .y_mm, 0, 0, 0, 0) + PICKUP_ORIGIN   ; 現場測試版：先不做旋轉，只沿 BASE 做 XY 平移
  ELSE
    found = 0
  END

  IF found == 0 THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END

  ; LAPPRO 預設沿「目前 TOOL」Z 軸退開，方向依賴當下有沒有切 TOOL、容易跟安裝角度對不上。
  ; 改成在 target_pt 所在的桌面座標系 (BASE ba) 裡沿 Z 手動平移 appro_mm，
  ; 不受 TOOL 安裝角度影響 (SHIFT 沿 BASE 座標軸平移，語法已對照 AS 語言參考手冊 9.2 節確認)。
  POINT target_pt_appro = SHIFT(target_pt BY 0, 0, appro_mm)
  ; 階段 3 集中動作要沿 TOOL 座標系移動 (DRAW 是 BASE 座標系，見手冊 6-2/6-8 節)，
  ; 改成一開始用複合變換值算好：target_pt + TRANS(...) 的第二項是相對於 target_pt
  ; 自身姿態 (即 TOOL 方向) 的偏移 (見手冊 3-14 節)，不是 BASE 方向。
  POINT target_conv = target_pt + TRANS(converge_dx, converge_dy, 0, 0, 0, 0)

  robot_busy = 1
  SPEED 70 MM/S ALWAYS   ; ★ 絕對速度，待現場測試調整
  TOOL ha_pickup                        ; PICKUP 專用姿勢/進退方向，結束前一定要切回 RIGHT_SPATULA

  ; 階段 1: 就緒
  LMOVE target_pt_appro
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    TOOL RIGHT_SPATULA
    robot_busy = 0
    RETURN
  END

  ; 階段 2: 下降
  LMOVE target_pt
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    TOOL RIGHT_SPATULA
    robot_busy = 0
    RETURN
  END

  ; 階段 3: 集中 (方向與 F60_F 相對，佔位示意，待現場調整)
  LMOVE target_conv
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    TOOL RIGHT_SPATULA
    robot_busy = 0
    RETURN
  END

  ; 階段 4: 抬起 (同樣改用 SHIFT，不沿 TOOL Z 軸退開)
  ; 用 target_conv 而非 HERE：CP ON 連續軌跡下，LMOVE 完不一定真的停在教點上，
  ; 直接引用階段 3 的目標點位比讀「目前位置」準確。
  POINT depart_pt = SHIFT(target_conv BY 0, 0, appro_mm)
  LMOVE depart_pt
  CALL SYNC_STEP(ok)
  IF ok == 0 THEN
    CALL SEND_LINE("ERROR,E4023")
    TOOL RIGHT_SPATULA
    robot_busy = 0
    RETURN
  END

  ; 階段 5: 移動至切割區 — 對應 F60_F 的 WORK_CHOP_ZONE，本臂用壓點偏移 PRESS_CHOP_ZONE。
  ; 比照階段 1-4 拆成 4 個子階段。
  IF .$location == "PICKUP_CUCUMBER" OR .$location == "PICKUP_CARROT" OR .$location == "PICKUP_ROMAINE" THEN
    ; 階段 5a: 就緒 — 兩臂移到切割區正上方
    POINT chop_appro_pt = SHIFT(PRESS_CHOP_ZONE BY 0, 0, appro_mm)
    LMOVE chop_appro_pt
    CALL SYNC_STEP(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 5b: 下降 — 下降到放置高度
    LMOVE PRESS_CHOP_ZONE
    CALL SYNC_STEP(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 5c: 散開 — 兩臂往外移動放開食材 (集中動作的相反，沿 TOOL 座標系移動)
    POINT chop_spread_pt = PRESS_CHOP_ZONE + TRANS(chop_spread_dx, chop_spread_dy, 0, 0, 0, 0)
    LMOVE chop_spread_pt
    CALL SYNC_STEP(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 5d: 抬起 — 兩臂抬起離開切割區
    POINT chop_depart_pt = SHIFT(chop_spread_pt BY 0, 0, appro_mm)
    LMOVE chop_depart_pt
    CALL SYNC_STEP(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END
  END

  TOOL RIGHT_SPATULA
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
; 現場手動測試用，跳過 SYNC_STEP，單臂直接跑一次 PICKUP_ORIGIN 附近的移動序列，
; 保留現狀不修改：.$location 在這支測試程式沒有參數可用，階段 5 那個 IF 恆為 false。
.PROGRAM DO_PICKUP_test()
  TOOL ha_pickup
  LMOVE PICKUP_ORIGIN
  POINT target_pt = TRANS(90, 0, 0, 0, 0, 0) + PICKUP_ORIGIN
  POINT target_pt = target_pt + TRANS(0, 0, 0, 0, 0, 0)
  ; LAPPRO 預設沿「目前 TOOL」Z 軸退開，方向依賴當下有沒有切 TOOL、容易跟安裝角度對不上。
  ; 改成在 target_pt 所在的桌面座標系 (BASE ba) 裡沿 Z 手動平移 appro_mm，
  ; 不受 TOOL 安裝角度影響 (SHIFT 沿 BASE 座標軸平移，語法已對照 AS 語言參考手冊 9.2 節確認)。
  POINT target_pt_appro = SHIFT(target_pt BY 0, 0, 50)
  ; 階段 3 集中動作要沿 TOOL 座標系移動 (DRAW 是 BASE 座標系，見手冊 6-2/6-8 節)，
  ; 改成一開始用複合變換值算好：target_pt + TRANS(...) 的第二項是相對於 target_pt
  ; 自身姿態 (即 TOOL 方向) 的偏移 (見手冊 3-14 節)，不是 BASE 方向。
  POINT target_pt_conve = target_pt + TRANS(0, -30, 0, 0, 0, 0)
  robot_busy = 1
  SPEED 70 MM/S ALWAYS   ; ★ 絕對速度，待現場測試調整
  TOOL ha_pickup                        ; PICKUP 專用姿勢/進退方向，結束前一定要切回 RIGHT_SPATULA
  ; 階段 1: 就緒
  ;LMOVE target_pt_appro
  ; 階段 2: 下降
  LMOVE target_pt
  ; 階段 3: 集中 (方向與 F60_F 相對，佔位示意，待現場調整)
  LMOVE target_pt_conve
  ; 階段 4: 抬起 (同樣改用 SHIFT，不沿 TOOL Z 軸退開)
  ; 用 target_pt_conve 而非 HERE：CP ON 連續軌跡下，LMOVE 完不一定真的停在教點上，
  ; 直接引用階段 3 的目標點位比讀「目前位置」準確。
  POINT depart_pt = SHIFT(target_pt_conve BY 0, 0, appro_mm)
  LMOVE depart_pt
  ; 階段 5: 移動至切割區 — 對應 F60_F 的 WORK_CHOP_ZONE，本臂用壓點偏移 PRESS_CHOP_ZONE
  IF .$location == "PICKUP_CUCUMBER" OR .$location == "PICKUP_CARROT" OR .$location == "PICKUP_ROMAINE" THEN
    POINT chop_appro_pt = SHIFT(PRESS_CHOP_ZONE BY 0, 0, appro_mm)
    LMOVE chop_appro_pt
    CALL SYNC_STEP(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END
    LMOVE PRESS_CHOP_ZONE
    CALL SYNC_STEP(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END
  END
  TOOL RIGHT_SPATULA
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
.PROGRAM DO_CHOP(.$food, .cuts, .thick)
  IF .cuts < 1 OR .cuts > 20 OR .thick <= 0 THEN
    CALL SEND_LINE("ERROR,E4005")
    RETURN
  END

  ; 根據菜色設定下壓高度，生菜不支援（已改為直接進混拌區）
  SCASE .$food OF
  SVALUE "CUCUMBER":
    press_mm = 15.0    ; 小黃瓜
  SVALUE "CARROT":
    press_mm = 12.0    ; 紅蘿蔔（較硬，減少壓力）
  ANY:
    CALL SEND_LINE("ERROR,E4005")  ; 其他菜色不支援
    RETURN
  END

  robot_busy = 1
  SPEED 50 MM/S ALWAYS   ; ★ 絕對速度，待現場測試調整
  LAPPRO PRESS_CHOP_ZONE, appro_mm
  LMOVE PRESS_CHOP_ZONE

  i = 0
  DO
    DRAW 0, 0, -press_mm           ; 先壓住食材

    CALL SYNC_STEP(ok)                  ; sync A：通知 F60_F 已壓好，可以下刀
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END

    CALL SYNC_STEP(ok)                  ; sync B：等 F60_F 切完這一刀
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      robot_busy = 0
      RETURN
    END

    DRAW 0, 0, press_mm            ; 鬆開，準備下一刀
    DRAW .thick, 0, 0                   ; 隨切割步進
    i = i + 1
  UNTIL i >= .cuts

  LDEPART appro_mm
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
; F60_R 只在 POUR 時參與 (跟 F60_F 在目的地一起傾倒)，不需要真的搬到來源撈取，
; 來源參數只做驗證用；SCOOP/PUSH 是 F60_F 單獨執行，PC 端不會把這兩種方式送給 F60_R。
.PROGRAM DO_PLACE(.$source, .$location, .$method)
  IF .$source <> "MIX_ZONE" THEN
    CALL SEND_LINE("ERROR,E4002")
    RETURN
  END

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
  IF .$method <> "POUR" THEN
    CALL SEND_LINE("ERROR,E4001")
    RETURN
  END

  robot_busy = 1
  SPEED 70 MM/S ALWAYS   ; ★ 絕對速度，待現場測試調整
  TOOL ha_pickup                        ; PLACE 專用姿勢/進退方向，結束前一定要切回 RIGHT_SPATULA
  LAPPRO target_pt, appro_mm
  LMOVE target_pt

  IF .$method == "POUR" THEN
    CALL SYNC_STEP(ok)                  ; 與 F60_F 會合，一起傾倒
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END
    TDRAW 0, 0, 0, 0, pour_tilt_deg, 0, 20      ; 雙鏟對合傾倒手勢 (角度依治具調整)
    TDRAW 0, 0, 0, 0, -pour_tilt_deg, 0, 20
  END

  LDEPART appro_mm
  TOOL RIGHT_SPATULA
  robot_busy = 0
  CALL SEND_LINE("OK")
.END
.PROGRAM DO_RTURN45(.ok)
  LMOVE rturn45_ready
  BREAK
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn45_down
  BREAK
  LMOVE rturn45_turn
  BREAK
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn45_down
  BREAK
  LMOVE rturn45_ready
  BREAK
  CALL SYNC_STEP(s)
  .ok = s
.END
.PROGRAM DO_RTURN90(.ok)
  LMOVE rturn90_ready
  BREAK
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn90_down
  BREAK
  LMOVE rturn90_turn
  BREAK
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn90_down
  BREAK
  LMOVE rturn90_ready
  BREAK
  CALL SYNC_STEP(s)
  .ok = s
.END
.PROGRAM DO_RTURN135(.ok)
  LMOVE rturn135_ready
  BREAK
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn135_down
  BREAK
  LMOVE rturn135_turn
  BREAK
  LMOVE rturn135_turn10
  BREAK
  CALL SYNC_STEP(s)
  IF s == 0 THEN
    .ok = 0
    RETURN
  END

  LMOVE rturn135_turn20
  BREAK
  LMOVE rturn135_ready
  BREAK
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
    ; 階段 1：90°/90° 配對
    CALL DO_RTURN90(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE ba
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 2：135°/45° 配對 (本臂 45°)
    CALL DO_RTURN45(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE ba
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    ; 階段 3：45°/135° 配對 (本臂 135°)
    CALL DO_RTURN135(ok)
    IF ok == 0 THEN
      CALL SEND_LINE("ERROR,E4023")
      BASE ba
      TOOL RIGHT_SPATULA
      robot_busy = 0
      RETURN
    END

    i = i + 1
  UNTIL i >= .cycles

  BASE ba
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
  SPEED 30 MM/S ALWAYS   ; ★ 絕對速度，待現場測試調整
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
	; F60_R_右臂_GBK
	; @@@ HISTORY @@@
	; 01.08.2026 18:24:57
	;
	; @@@ INSPECTION @@@
	; @@@ CONNECTION @@@
	; Rs07_R
	; 192.168.5.7
	; 23
	; @@@ PROGRAM @@@
	; 0:INIT_SWITCHES:F
	; .PC
	; 0:INIT_CONST:F
	; 0:INIT_POINTS:F
	; 0:INIT_TOOL:F
	; 0:heartput:F
	; 0:MAIN:F
	; 0:DISCONNECT:F
	; 0:CLEAN_SOCKET:F
	; 0:OPEN_LISTEN:F
	; 0:WAIT_ACCEPT:F
	; .accepted
	; 0:DO_HANDSHAKE:F
	; .ok
	; 0:RECV_LINE:F
	; .rok
	; 0:SEND_LINE:F
	; 0:SPLIT_CSV:F
	; 0:DISPATCH:F
	; 0:WAIT_SIGNAL:F
	; .sig_no
	; .timeout_sec
	; .ok
	; 0:WAIT_SIGNAL_OFF:F
	; .sig_no
	; .timeout_sec
	; .ok
	; 0:DO_IOTEST:F
	; .op
	; 0:SYNC_STEP:F
	; .ok
	; 0:DO_PICKUP:F
	; 0:DO_CHOP:F
	; .cuts
	; .thick
	; 0:DO_PLACE:F
	; 0:DO_RTURN45:F
	; .ok
	; 0:DO_RTURN90:F
	; .ok
	; 0:DO_RTURN135:F
	; .ok
	; 0:DO_FLIP:F
	; .cycles
	; .speed_pct
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
