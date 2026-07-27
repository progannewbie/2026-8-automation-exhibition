; =====================================================================
; SmartCook 機械手臂控制程式 — F60_F (左臂 / 主切割臂)
; 語言: Kawasaki AS Language
; 版本: v0.1 (骨架 skeleton，對應 PC 端 comms_connection_skeleton.py)
; 對應規格書: COMMAND_SPECIFICATION.md / CONNECTION_PROTOCOL.md /
;             OBJECT_DEFINITIONS_v1.1.md / SmartCook_信號分配表.docx
;
; 三個待確認事項 (請機械/電控工程師覆核後移除本段註解):
;   1. 通訊通道: 下方 OPEN "ETHERNET1:" 等敘述為 Kawasaki Ethernet
;      Slave 標準寫法示意，實際通道名稱/編號需依控制器韌體版本
;      的 AS 手冊與教示盒「乙太網路設定」畫面核對。IP(192.168.5.2)
;      與 Port(9000) 是在控制器網路設定中綁定，本程式不重複設定。
;   2. 所有 PTEACH 標記的點位皆為佔位值 TRANS(0,0,0,0,0,0)，需在
;      現場用教示盒實際教點後覆蓋 (參照 CALIBRATION_POINTS.csv，
;      目前仍為「待標定」)。
;   3. I/O 訊號編號 (SIG_OUT_*/SIG_IN_*) 為佔位編號 1–4，對應
;      SmartCook_信號分配表.docx 中 DO_F_1/DO_F_2/DO_R_1/DO_R_2，
;      該文件註明「待你手動補充」，實際腳位需與 F60_R 對接配線後
;      一併確認。
; =====================================================================

; ---------------------------------------------------------------------
; 常數
; ---------------------------------------------------------------------
.PROGRAM CONST_F()
  10 string THIS_ARM$
  20 THIS_ARM$ = "F60_F"

  ; --- I/O 訊號編號 (雙臂對接，佔位值，待電控確認) ---
  30 integer SIG_OUT_PRESS_DONE     ; DO_F_1: 壓定完成信號 → F60_R
  40 integer SIG_OUT_LIFT_DONE      ; DO_F_2: 提鏟完成信號 → F60_R
  50 integer SIG_IN_CHOP_DONE       ; DO_R_1: 落刀完成信號 ← F60_R
  60 integer SIG_IN_STEP_DONE       ; DO_R_2: 步進完成信號 ← F60_R
  70 SIG_OUT_PRESS_DONE = 1
  80 SIG_OUT_LIFT_DONE  = 2
  90 SIG_IN_CHOP_DONE    = 1
  100 SIG_IN_STEP_DONE   = 2

  ; --- 動作參數 (可依現場試切調整) ---
  110 real APPRO_MM, CHOP_DOWN_MM, FLIP_UP_MM
  120 APPRO_MM     = 80.0    ; 取放料上方安全接近距離
  130 CHOP_DOWN_MM = 40.0    ; 每刀下壓深度
  140 FLIP_UP_MM   = 90.0    ; 翻炒上翻高度 (< 100mm，見規格)

  ; --- 逾時設定 (秒) ---
  150 real TIMEOUT_IO_SEC, TIMEOUT_FLIP_SEC
  160 TIMEOUT_IO_SEC   = 5.0
  170 TIMEOUT_FLIP_SEC = 5.0
.END

; ---------------------------------------------------------------------
; 點位宣告 (PTEACH = 待現場教點，目前為佔位座標)
; ---------------------------------------------------------------------
.PROGRAM TEACH_POINTS_F()
  10  PICKUP_CUCUMBER = TRANS(0,0,0,0,0,0)   ; PTEACH
  20  PICKUP_ROMAINE  = TRANS(0,0,0,0,0,0)   ; PTEACH
  30  PICKUP_RED_LEAF = TRANS(0,0,0,0,0,0)   ; PTEACH
  40  WAIT_ZONE       = TRANS(0,0,0,0,0,0)   ; PTEACH
  50  MIX_ZONE        = TRANS(0,0,0,0,0,0)   ; PTEACH
  60  WORK_CHOP_ZONE  = TRANS(0,0,0,0,0,0)   ; PTEACH
  70  WORK_FLIP_ZONE  = TRANS(0,0,0,0,0,0)   ; PTEACH
  80  SALAD_BOWL      = TRANS(0,0,0,0,0,0)   ; PTEACH (ArUco ID 102 輔助標定)
  90  WASTE_CORNER    = TRANS(0,0,0,0,0,0)   ; PTEACH
  100 HOME_LEFT       = TRANS(0,0,0,0,0,0)   ; PTEACH (手工標定，示教盒)
.END

; ---------------------------------------------------------------------
; 全域執行狀態
; ---------------------------------------------------------------------
.PROGRAM STATE_F()
  10 integer robot_busy
  20 robot_busy = 0
  30 string fld$[8]
  40 integer nfld
.END

; =====================================================================
; MAIN — 程式進入點
; =====================================================================
.PROGRAM MAIN()
  10  CALL CONST_F()
  20  CALL TEACH_POINTS_F()
  30  CALL STATE_F()
  40  SPEED 30 ALWAYS
  50  ACCURACY 1
  60  SIGNAL -SIG_OUT_PRESS_DONE
  70  SIGNAL -SIG_OUT_LIFT_DONE
  80  LMOVE HOME_LEFT
  90
  100 DO                                   ; 展場常駐迴圈：斷線後自動回來重新等待連線
  110   CALL WAIT_CONNECT()
  120   integer conn_lost
  130   conn_lost = 0
  140   DO
  150     CALL RECV_LINE()                 ; 讀入一行 → 存入 line$，結果存 recv_ok
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
; 連線與握手
; ---------------------------------------------------------------------
.PROGRAM WAIT_CONNECT()
  ; 開啟 Ethernet Slave 通道並等待 PC 連線 + 握手
  ; 待辦: 依控制器實際乙太網路槽位確認通道名稱 (示意名 "ETHERNET1:")
  10 string line$
  20 integer recv_ok
  30 OPEN "ETHERNET1:" AS 1
  40 LINE INPUT #1, line$                  ; 預期收到 "connect"
  50 IF line$ = "connect" THEN
  60   PRINT #1, "BOARD_ID,F60_CTRL_001"
  70 ELSE
  80   PRINT #1, "ERROR,E4021"
  90 END
.END

; ---------------------------------------------------------------------
; 讀取一行指令 (以 \n 結尾)，失敗代表連線中斷
; ---------------------------------------------------------------------
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
  90    ELSE IF fld$[1] = "STATUS" THEN
  100     PRINT #1, "BUSY"
  110   ELSE IF fld$[1] = "READY" THEN
  120     PRINT #1, "BUSY"
  130   ELSE
  140     PRINT #1, "BUSY"
  150   END
  160   RETURN
  170 END
  180
  190 IF fld$[1] = "PICKUP" THEN
  200   CALL DO_PICKUP(fld$[2], fld$[3])
  210 ELSE IF fld$[1] = "CHOP" THEN
  220   CALL DO_CHOP(fld$[2], VAL(fld$[3]), VAL(fld$[4]))
  230 ELSE IF fld$[1] = "PLACE" THEN
  240   CALL DO_PLACE(fld$[2], fld$[3])
  250 ELSE IF fld$[1] = "FLIP" THEN
  260   CALL DO_FLIP(VAL(fld$[2]), VAL(fld$[3]))
  270 ELSE IF fld$[1] = "HOME" THEN
  280   CALL DO_HOME(fld$[2])
  290 ELSE IF fld$[1] = "STOP" THEN
  300   CALL DO_STOP()
  310 ELSE IF fld$[1] = "RESET" THEN
  320   CALL DO_RESET()
  330 ELSE IF fld$[1] = "STATUS" THEN
  340   CALL DO_STATUS(fld$[2])
  350 ELSE IF fld$[1] = "READY" THEN
  360   CALL DO_READY(fld$[2])
  370 ELSE
  380   PRINT #1, "ERROR,E4021"           ; 未知指令
  390 END
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

; ---------------------------------------------------------------------
; PICKUP,<LOCATION>,<ARM>
; ---------------------------------------------------------------------
.PROGRAM DO_PICKUP(location$, arm$)
  10 IF arm$ <> THIS_ARM$ THEN
  20   PRINT #1, "ERROR,E4003"
  30   RETURN
  40 END
  50 integer found
  60 found = 1
  70 IF location$ = "PICKUP_CUCUMBER" THEN
  80   dest = PICKUP_CUCUMBER
  90 ELSE IF location$ = "PICKUP_ROMAINE" THEN
  100  dest = PICKUP_ROMAINE
  110 ELSE IF location$ = "PICKUP_RED_LEAF" THEN
  120  dest = PICKUP_RED_LEAF
  130 ELSE IF location$ = "WAIT_ZONE" THEN
  140  dest = WAIT_ZONE
  150 ELSE IF location$ = "MIX_ZONE" THEN
  160  dest = MIX_ZONE
  170 ELSE
  180  found = 0
  190 END
  200 IF found = 0 THEN
  210   PRINT #1, "ERROR,E4002"
  220   RETURN
  230 END
  240 robot_busy = 1
  250 SPEED 40 ALWAYS
  260 APPRO dest, APPRO_MM
  270 LMOVE dest
  280 ; TODO: 依實際夾具/鏟取動作插入取料手勢 (鏟子插入角度、聚攏)
  290 DEPART APPRO_MM
  300 robot_busy = 0
  310 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM>
; 由左鏟(開刃)執行下壓切割，每刀完成後與 F60_R 交握 (壓點步進)
; ---------------------------------------------------------------------
.PROGRAM DO_CHOP(food$, cuts, thick)
  10 IF food$ <> "CUCUMBER" AND food$ <> "ROMAINE" THEN
  20   PRINT #1, "ERROR,E4004"
  30   RETURN
  40 END
  50 IF cuts < 1 OR cuts > 20 OR thick <= 0 THEN
  60   PRINT #1, "ERROR,E4005"
  70   RETURN
  80 END
  90 robot_busy = 1
  100 SPEED 30 ALWAYS
  110 APPRO WORK_CHOP_ZONE, APPRO_MM
  120 LMOVE WORK_CHOP_ZONE
  130 integer i, ok
  140 i = 0
  150 DO
  160   DRAW 0, 0, -CHOP_DOWN_MM         ; 下壓切割
  170   SIGNAL SIG_OUT_LIFT_DONE         ; 通知 F60_R: 本刀已完成 (DO_F_2)
  180   CALL WAIT_SIGNAL(SIG_IN_STEP_DONE, TIMEOUT_IO_SEC, ok)
  190   SIGNAL -SIG_OUT_LIFT_DONE
  200   IF ok = 0 THEN
  210     PRINT #1, "ERROR,E4023"        ; I/O 信號超時 (雙臂握手)
  220     robot_busy = 0
  230     RETURN
  240   END
  250   DRAW 0, 0, CHOP_DOWN_MM          ; 提鏟
  260   DRAW thick, 0, 0                 ; 步進到下一刀位置
  270   i = i + 1
  280 UNTIL i >= cuts
  290 DEPART APPRO_MM
  300 robot_busy = 0
  310 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; PLACE,<LOCATION>,<METHOD>
; ---------------------------------------------------------------------
.PROGRAM DO_PLACE(location$, method$)
  10 integer found
  20 found = 1
  30 IF location$ = "SALAD_BOWL" THEN
  40   dest = SALAD_BOWL
  50 ELSE IF location$ = "WAIT_ZONE" THEN
  60   dest = WAIT_ZONE
  70 ELSE IF location$ = "MIX_ZONE" THEN
  80   dest = MIX_ZONE
  90 ELSE IF location$ = "WASTE_CORNER" THEN
  100  dest = WASTE_CORNER
  110 ELSE
  120  found = 0
  130 END
  140 IF found = 0 THEN
  150   PRINT #1, "ERROR,E4002"
  160   RETURN
  170 END
  180 IF method$ <> "POUR" AND method$ <> "SCOOP" AND method$ <> "PUSH" THEN
  190   PRINT #1, "ERROR,E4001"
  200   RETURN
  210 END
  220 robot_busy = 1
  230 SPEED 40 ALWAYS
  240 APPRO dest, APPRO_MM
  250 LMOVE dest
  260 IF method$ = "POUR" THEN
  270   SIGNAL SIG_OUT_PRESS_DONE        ; 通知 F60_R 同步傾倒 (DO_F_1)
  280   integer ok
  290   CALL WAIT_SIGNAL(SIG_IN_CHOP_DONE, TIMEOUT_IO_SEC, ok)
  300   SIGNAL -SIG_OUT_PRESS_DONE
  310   TWRIST 90                        ; 雙鏟對合傾倒手勢 (角度依實際治具調整)
  320   TWRIST 0
  330 ELSE IF method$ = "SCOOP" THEN
  340   ; 平放鏟子放置，無需額外動作
  350 ELSE IF method$ = "PUSH" THEN
  360   DRAW 0, 60, 0                    ; 推動廢料至角落 (方向/距離待現場調整)
  370 END
  380 DEPART APPRO_MM
  390 robot_busy = 0
  400 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; FLIP,<NUM_CYCLES>,<SPEED_PERCENT> — 左臂為主導方 (先上翻)
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
  150   DRAW 0, 0, FLIP_UP_MM            ; 左鏟上翻
  160   SIGNAL SIG_OUT_LIFT_DONE         ; 通知 F60_R 本循環開始
  170   CALL WAIT_SIGNAL(SIG_IN_STEP_DONE, TIMEOUT_FLIP_SEC, ok)
  180   SIGNAL -SIG_OUT_LIFT_DONE
  190   IF ok = 0 THEN
  200     PRINT #1, "ERROR,E4023"
  210     robot_busy = 0
  220     RETURN
  230   END
  240   DRAW 0, 0, -FLIP_UP_MM
  250   i = i + 1
  260 UNTIL i >= cycles
  270 robot_busy = 0
  280 PRINT #1, "OK"
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
  60 SPEED 20 ALWAYS                     ; 復歸使用較低安全速度
  70 LMOVE HOME_LEFT
  80 robot_busy = 0
  90 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; STOP — 緊急停止
; ---------------------------------------------------------------------
.PROGRAM DO_STOP()
  10 HOLD                                ; 立即停止當前動作
  20 SIGNAL -SIG_OUT_PRESS_DONE
  30 SIGNAL -SIG_OUT_LIFT_DONE
  40 robot_busy = 0
  50 PRINT #1, "OK"
.END

; ---------------------------------------------------------------------
; RESET — 清除狀態，重新初始化
; ---------------------------------------------------------------------
.PROGRAM DO_RESET()
  10 ERESET                              ; 清除錯誤狀態 (依控制器實際指令核對)
  20 robot_busy = 0
  30 SIGNAL -SIG_OUT_PRESS_DONE
  40 SIGNAL -SIG_OUT_LIFT_DONE
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
