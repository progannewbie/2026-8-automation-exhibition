; =====================================================================
; SmartCook 機械手臂控制程式 — F60_R (右臂 / 輔助固定臂)
; 語言: Kawasaki AS Language
; 版本: v0.1 (骨架 skeleton，對應 PC 端 comms_connection_skeleton.py)
; 對應規格書: COMMAND_SPECIFICATION.md / CONNECTION_PROTOCOL.md /
;             OBJECT_DEFINITIONS_v1.1.md / SmartCook_信號分配表.docx
;
; 請與 F60_F_左臂.as 對照閱讀，兩者共用同一組雙臂對接 I/O 訊號。
; 三個待確認事項同 F60_F_左臂.as 開頭說明 (通訊通道名稱 / 教點座標 /
; I/O 訊號腳位)，此處不重複。
;
; 架構說明:
;   MAIN            — 處理 PC 端 TCP/CSV 指令 (HOME/STOP/RESET/
;                      STATUS/READY/FLIP/PLACE，必要時 PICKUP)
;   ASSIST_WATCHER  — 背景常駐任務，監聽 F60_F 傳來的 I/O 交握信號，
;                      即時完成「壓住食材/隨刀步進/協同傾倒」等動作，
;                      不經過 PC，因為切刀節奏需要毫秒級即時反應。
;                      待辦: 需在教示盒將此程式指派為獨立並行任務，
;                      與 MAIN 同時常駐執行 (雙任務共用全域變數)。
; =====================================================================

.PROGRAM CONST_R()
  10 string THIS_ARM$
  20 THIS_ARM$ = "F60_R"

  ; --- I/O 訊號編號 (與 F60_F 對接，佔位值，待電控確認) ---
  30 integer SIG_OUT_CHOP_DONE      ; DO_R_1: 落刀完成信號 → F60_F
  40 integer SIG_OUT_STEP_DONE      ; DO_R_2: 步進完成信號 → F60_F
  50 integer SIG_IN_PRESS_DONE      ; DO_F_1: 壓定完成信號 ← F60_F
  60 integer SIG_IN_LIFT_DONE       ; DO_F_2: 提鏟完成信號 ← F60_F
  70 SIG_OUT_CHOP_DONE = 1
  80 SIG_OUT_STEP_DONE = 2
  90 SIG_IN_PRESS_DONE = 1
  100 SIG_IN_LIFT_DONE  = 2

  ; --- 動作參數 (可依現場試切調整) ---
  110 real APPRO_MM, PRESS_DOWN_MM, STEP_MM, FLIP_DOWN_MM
  120 APPRO_MM      = 80.0
  130 PRESS_DOWN_MM = 15.0    ; 壓住食材下壓量 (輕壓，勿過力)
  140 STEP_MM       = 4.0     ; 壓點隨切割步進距離 (應與 CHOP 厚度一致)
  150 FLIP_DOWN_MM  = 90.0    ; 翻炒下壓翻動高度

  ; --- 逾時設定 (秒) ---
  160 real TIMEOUT_IO_SEC, TIMEOUT_FLIP_SEC
  170 TIMEOUT_IO_SEC   = 5.0
  180 TIMEOUT_FLIP_SEC = 5.0
.END

; ---------------------------------------------------------------------
; 點位宣告 (PTEACH = 待現場教點，目前為佔位座標)
; ---------------------------------------------------------------------
.PROGRAM TEACH_POINTS_R()
  10  PRESS_CHOP_ZONE = TRANS(0,0,0,0,0,0)   ; PTEACH: WORK_CHOP_ZONE 對應壓點
  20  MIX_ZONE        = TRANS(0,0,0,0,0,0)   ; PTEACH
  30  WORK_FLIP_ZONE  = TRANS(0,0,0,0,0,0)   ; PTEACH
  40  SALAD_BOWL      = TRANS(0,0,0,0,0,0)   ; PTEACH (ArUco ID 102 輔助標定)
  50  PICKUP_RED_LEAF = TRANS(0,0,0,0,0,0)   ; PTEACH (雙鏟協作聚攏)
  60  HOME_RIGHT      = TRANS(0,0,0,0,0,0)   ; PTEACH (手工標定，示教盒)
.END

; ---------------------------------------------------------------------
; 全域執行狀態
; ---------------------------------------------------------------------
.PROGRAM STATE_R()
  10 integer robot_busy
  20 robot_busy = 0
  30 string fld$[8]
  40 integer nfld
.END

; =====================================================================
; MAIN — 程式進入點 (PC 指令通道)
; =====================================================================
.PROGRAM MAIN()
  10  CALL CONST_R()
  20  CALL TEACH_POINTS_R()
  30  CALL STATE_R()
  40  SPEED 30 ALWAYS
  50  ACCURACY 1
  60  SIGNAL -SIG_OUT_CHOP_DONE
  70  SIGNAL -SIG_OUT_STEP_DONE
  80  LMOVE HOME_RIGHT
  90
  100 DO                                   ; 展場常駐迴圈：斷線後自動回來重新等待連線
  110   CALL WAIT_CONNECT()
  120   integer conn_lost
  130   conn_lost = 0
  140   DO
  150     CALL RECV_LINE()
  160     IF recv_ok = 0 THEN
  170       conn_lost = 1
  180     ELSE
  190       CALL SPLIT_CSV(line$)
  200       CALL DISPATCH()
  210     END
  220   UNTIL conn_lost = 1
  230   CLOSE #1
  240 UNTIL 1 = 0
.END

; ---------------------------------------------------------------------
; 背景常駐任務 — 監聽 F60_F 的 I/O 交握信號，即時協同動作
; 待辦: 教示盒指派為獨立並行任務，與 MAIN 同時常駐執行
; ---------------------------------------------------------------------
.PROGRAM ASSIST_WATCHER()
  10 CALL CONST_R()                        ; 常數與點位在各任務各自載入一次
  20 CALL TEACH_POINTS_R()
  30 DO
  40   IF SIG(SIG_IN_LIFT_DONE) = 1 THEN
  50     CALL DO_ASSIST_PRESS_STEP()
  60   ELSE IF SIG(SIG_IN_PRESS_DONE) = 1 THEN
  70     CALL DO_ASSIST_POUR()
  80   END
  90 UNTIL 1 = 0
.END

; 每刀壓點下壓 + 步進，回報 F60_F 可提鏟繼續下一刀
.PROGRAM DO_ASSIST_PRESS_STEP()
  10 robot_busy = 1
  20 LMOVE PRESS_CHOP_ZONE
  30 DRAW 0, 0, -PRESS_DOWN_MM
  40 DRAW STEP_MM, 0, 0
  50 SIGNAL SIG_OUT_STEP_DONE              ; DO_R_2: 步進完成 → F60_F
  60 integer ok
  70 CALL WAIT_SIGNAL_OFF(SIG_IN_LIFT_DONE, TIMEOUT_IO_SEC, ok)
  80 SIGNAL -SIG_OUT_STEP_DONE
  90 robot_busy = 0
.END

; 沙拉盤裝盤：右鏟托底配合左鏟傾倒
.PROGRAM DO_ASSIST_POUR()
  10 robot_busy = 1
  20 LMOVE SALAD_BOWL
  30 TWRIST 90                             ; 雙鏟對合傾倒手勢 (角度依實際治具調整)
  40 SIGNAL SIG_OUT_CHOP_DONE              ; DO_R_1: 就位完成 → F60_F
  50 integer ok
  60 CALL WAIT_SIGNAL_OFF(SIG_IN_PRESS_DONE, TIMEOUT_IO_SEC, ok)
  70 SIGNAL -SIG_OUT_CHOP_DONE
  80 TWRIST 0
  90 robot_busy = 0
.END

; ---------------------------------------------------------------------
; 連線與握手
; ---------------------------------------------------------------------
.PROGRAM WAIT_CONNECT()
  10 string line$
  20 integer recv_ok
  30 OPEN "ETHERNET1:" AS 1
  40 LINE INPUT #1, line$                  ; 預期收到 "connect"
  50 IF line$ = "connect" THEN
  60   PRINT #1, "BOARD_ID,F60_CTRL_002"
  70 ELSE
  80   PRINT #1, "ERROR,E4021"
  90 END
.END

.PROGRAM RECV_LINE()
  10 LINE INPUT #1, line$
  20 recv_ok = 1
.END

; ---------------------------------------------------------------------
; CSV 切割: line$ → fld$[1..nfld]
; ---------------------------------------------------------------------
.PROGRAM SPLIT_CSV(line$)
  10 integer i, p
  20 string rest$
  30 FOR i = 1 TO 8
  40   fld$[i] = ""
  50 END
  60 nfld = 0
  70 rest$ = line$
  80 DO
  90   p = INSTR(1, rest$, ",")
  100  nfld = nfld + 1
  110  IF p = 0 THEN
  120    fld$[nfld] = rest$
  130    rest$ = ""
  140  ELSE
  150    fld$[nfld] = MID$(rest$, 1, p - 1)
  160    rest$ = MID$(rest$, p + 1, LEN(rest$) - p)
  170  END
  180 UNTIL rest$ = "" OR nfld >= 8
.END

; ---------------------------------------------------------------------
; 指令分派
; ---------------------------------------------------------------------
.PROGRAM DISPATCH()
  10  IF fld$[1] = "HEARTBEAT" THEN
  20    PRINT #1, "HEARTBEAT_ACK"
  30    RETURN
  40  END
  50
  60  IF robot_busy = 1 THEN
  70    IF fld$[1] = "STOP" THEN
  80      CALL DO_STOP()
  90    ELSE
  100     PRINT #1, "BUSY"
  110   END
  120   RETURN
  130 END
  140
  150 IF fld$[1] = "PICKUP" THEN
  160   CALL DO_PICKUP(fld$[2], fld$[3])
  170 ELSE IF fld$[1] = "PLACE" THEN
  180   CALL DO_PLACE(fld$[2], fld$[3])
  190 ELSE IF fld$[1] = "FLIP" THEN
  200   CALL DO_FLIP(VAL(fld$[2]), VAL(fld$[3]))
  210 ELSE IF fld$[1] = "HOME" THEN
  220   CALL DO_HOME(fld$[2])
  230 ELSE IF fld$[1] = "STOP" THEN
  240   CALL DO_STOP()
  250 ELSE IF fld$[1] = "RESET" THEN
  260   CALL DO_RESET()
  270 ELSE IF fld$[1] = "STATUS" THEN
  280   CALL DO_STATUS(fld$[2])
  290 ELSE IF fld$[1] = "READY" THEN
  300   CALL DO_READY(fld$[2])
  310 ELSE IF fld$[1] = "CHOP" THEN
  320   PRINT #1, "ERROR,E4021"           ; CHOP 一律送左臂，右臂不支援
  330 ELSE
  340   PRINT #1, "ERROR,E4021"
  350 END
.END

; ---------------------------------------------------------------------
; 訊號等待 (含逾時)，ok=1 成功 / ok=0 逾時
; ---------------------------------------------------------------------
.PROGRAM WAIT_SIGNAL(sig_no, timeout_sec, ok)
  10 real t0
  20 t0 = TIMER
  30 ok = 0
  40 DO
  50   IF SIG(sig_no) = 1 THEN
  60     ok = 1
  70     RETURN
  80   END
  90 UNTIL TIMER - t0 > timeout_sec
.END

.PROGRAM WAIT_SIGNAL_OFF(sig_no, timeout_sec, ok)
  10 real t0
  20 t0 = TIMER
  30 ok = 0
  40 DO
  50   IF SIG(sig_no) = 0 THEN
  60     ok = 1
  70     RETURN
  80   END
  90 UNTIL TIMER - t0 > timeout_sec
.END

; ---------------------------------------------------------------------
; PICKUP,<LOCATION>,<ARM> — 主要用於紅捲鬚雙鏟協作聚攏
; ---------------------------------------------------------------------
.PROGRAM DO_PICKUP(location$, arm$)
  10 IF arm$ <> THIS_ARM$ THEN
  20   PRINT #1, "ERROR,E4003"
  30   RETURN
  40 END
  50 IF location$ <> "PICKUP_RED_LEAF" THEN
  60   PRINT #1, "ERROR,E4002"
  70   RETURN
  80 END
  90 robot_busy = 1
  100 SPEED 40 ALWAYS
  110 APPRO PICKUP_RED_LEAF, APPRO_MM
  120 LMOVE PICKUP_RED_LEAF
  130 ; TODO: 低角度切入葉團底部，與左鏟對合成托 (雙鏟協作)
  140 DEPART APPRO_MM
  150 robot_busy = 0
  160 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; PLACE,<LOCATION>,<METHOD> — 主要用於中間位置托運 (SCOOP)
; ---------------------------------------------------------------------
.PROGRAM DO_PLACE(location$, method$)
  10 integer found
  20 found = 1
  30 IF location$ = "MIX_ZONE" THEN
  40   dest = MIX_ZONE
  50 ELSE IF location$ = "SALAD_BOWL" THEN
  60   dest = SALAD_BOWL
  70 ELSE
  80   found = 0
  90 END
  100 IF found = 0 THEN
  110   PRINT #1, "ERROR,E4002"
  120   RETURN
  130 END
  140 IF method$ <> "POUR" AND method$ <> "SCOOP" AND method$ <> "PUSH" THEN
  150   PRINT #1, "ERROR,E4001"
  160   RETURN
  170 END
  180 robot_busy = 1
  190 SPEED 40 ALWAYS
  200 APPRO dest, APPRO_MM
  210 LMOVE dest
  220 DEPART APPRO_MM
  230 robot_busy = 0
  240 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; FLIP,<NUM_CYCLES>,<SPEED_PERCENT> — 右臂為配合方 (F 上翻時，R 下壓翻)
; ---------------------------------------------------------------------
.PROGRAM DO_FLIP(cycles, speed_pct)
  10 IF cycles < 1 OR cycles > 20 THEN
  20   PRINT #1, "ERROR,E4005"
  30   RETURN
  40 END
  50 IF speed_pct < 1 OR speed_pct > 100 THEN
  60   PRINT #1, "ERROR,E4005"
  70   RETURN
  80 END
  90 robot_busy = 1
  100 SPEED speed_pct ALWAYS
  110 LMOVE WORK_FLIP_ZONE
  120 integer i, ok
  130 i = 0
  140 DO
  150   CALL WAIT_SIGNAL(SIG_IN_LIFT_DONE, TIMEOUT_FLIP_SEC, ok)   ; 等左鏟上翻開始
  160   IF ok = 0 THEN
  170     PRINT #1, "ERROR,E4023"
  180     robot_busy = 0
  190     RETURN
  200   END
  210   DRAW 0, 0, -FLIP_DOWN_MM          ; 右鏟下壓並翻
  220   SIGNAL SIG_OUT_STEP_DONE          ; 通知左鏟本循環完成
  230   DRAW 0, 0, FLIP_DOWN_MM
  240   CALL WAIT_SIGNAL_OFF(SIG_IN_LIFT_DONE, TIMEOUT_FLIP_SEC, ok)
  250   SIGNAL -SIG_OUT_STEP_DONE
  260   i = i + 1
  270 UNTIL i >= cycles
  280 robot_busy = 0
  290 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; HOME,<ARM>
; ---------------------------------------------------------------------
.PROGRAM DO_HOME(arm$)
  10 IF arm$ <> THIS_ARM$ THEN
  20   PRINT #1, "ERROR,E4003"
  30   RETURN
  40 END
  50 robot_busy = 1
  60 SPEED 20 ALWAYS
  70 LMOVE HOME_RIGHT
  80 robot_busy = 0
  90 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; STOP — 緊急停止
; ---------------------------------------------------------------------
.PROGRAM DO_STOP()
  10 HOLD
  20 SIGNAL -SIG_OUT_CHOP_DONE
  30 SIGNAL -SIG_OUT_STEP_DONE
  40 robot_busy = 0
  50 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; RESET — 清除狀態，重新初始化
; ---------------------------------------------------------------------
.PROGRAM DO_RESET()
  10 ERESET                              ; 依控制器實際指令核對
  20 robot_busy = 0
  30 SIGNAL -SIG_OUT_CHOP_DONE
  40 SIGNAL -SIG_OUT_STEP_DONE
  50 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; STATUS,<ARM> / READY,<ARM>
; ---------------------------------------------------------------------
.PROGRAM DO_STATUS(arm$)
  10 IF arm$ <> THIS_ARM$ THEN
  20   PRINT #1, "ERROR,E4003"
  30   RETURN
  40 END
  50 IF robot_busy = 1 THEN
  60   PRINT #1, "BUSY"
  70 ELSE
  80   PRINT #1, "OK"
  90 END
.END

.PROGRAM DO_READY(arm$)
  10 IF arm$ <> THIS_ARM$ THEN
  20   PRINT #1, "ERROR,E4003"
  30   RETURN
  40 END
  50 IF robot_busy = 1 THEN
  60   PRINT #1, "BUSY"
  70 ELSE
  80   PRINT #1, "OK"
  90 END
.END
