; CLAUDE ][ GS - SHR graphics client (640 mode, 4 colors, 80x25 text).
; Scrolling transcript + pinned input box + serial link to the bridge.
; Targets the IIgs SCC (slot 2, channel B) as used by KEGS Incoming mode.
; Loaded by DOS 3.3 BRUN at $4000; runs in 65816 native mode.

.setcpu "65816"
.segment "CODE"
.a8
.i8

; ---- zero page ----
destptr = $E0          ; 3 bytes: screen addr + bank ($E1)
strptr  = $E4          ; word: string pointer (bank 0)
glyphptr= $E6          ; word: font glyph pointer (bank 0)
curcol  = $E8          ; word: transcript column 0-79
currow  = $EA          ; word: transcript row
txtcolor= $EC          ; byte: color 0-3
coloff  = $ED          ; byte: txtcolor*16
tmp     = $EE          ; word scratch
srcp    = $08          ; word: splash draw source pointer ($08-$09 free)
srcrow  = $FD          ; word: splash row-start ($FD-$FE free; NOT $EB-$EE,
                       ;  those are txtcolor/coloff/tmp!)
tmp2    = $06          ; word scratch ($06-$07: free under Applesoft/ProDOS.
                       ;  NOT $D6 - that's Applesoft's auto-RUN lock flag, and
                       ;  scribbling on it wrecks BASIC after Ctrl-Reset)
rowcnt  = $DF          ; byte scratch
linelen = $DE          ; byte: input length
savecol = $DC          ; word: saved transcript col
saverow = $DA          ; word: saved transcript row
frame   = $D9          ; byte: spinner frame
firstbyte = $D5        ; byte: first real reply byte stashed by spinner
havefirst = $D4        ; byte: nonzero if firstbyte is valid
srcptr  = $D0          ; 3 bytes: scroll source pointer + bank ($D2)
colorpend = $D3        ; byte: nonzero if next reply byte is a color value
spinword = $D7         ; byte: index of current "thinking" word
bufptr  = $FA          ; 3 bytes: scrollback line pointer + bank ($FC).
                       ;  NOT $B0-$B2 - that's inside Applesoft's CHRGET
                       ;  routine (live code!); overwriting it breaks all of
                       ;  BASIC after Ctrl-Reset until a full reboot

; ---- layout (text rows 0-24) ----
TOP_ROW   = 0          ; scroll region top (header lives here and scrolls away)
START_ROW = 5          ; where the transcript cursor begins (below the header)
BOT_ROW   = 20         ; transcript bottom
RULE1_ROW = 21
INPUT_ROW = 22
RULE2_ROW = 23

; ---- SHR / IO ----
SHR_BASE   = $2000
NEWVIDEO   = $C029
BORDERCOL  = $C034
KBD        = $C000
KBDSTRB    = $C010
RDVBL      = $C019     ; bit7 toggles each vertical-blank (~60Hz)
SCC_STAT   = $C038     ; RR0: bit0=Rx avail, bit2=Tx empty
SCC_DATA   = $C03A
RBUF       = $1E00     ; 256-byte serial Rx ring buffer (bank 0, below the code)
EOT        = $04
CMD_COLOR  = $01       ; in-band: next byte sets txtcolor (1 gray/2 coral/3 white)
CMD_BULLET = $02       ; in-band: draw the white reply bullet here
CMD_QUIT   = $03       ; in-band: bridge says session over -> back to the menu
CMD_TOKEN  = $05       ; in-band: bridge issues a device token; we store it to disk
CMD_HEADER = $0E       ; in-band: header frame follows (title CR subtitle CR)

; ---- token sector (device pairing): RWTS a reserved sector on the boot disk.
;   RWTS is 8-bit DOS code (never touches M/X or the e-bit), so the token
;   helpers run in native 8-bit mode (sep #$30). Entry $BD00, the IOB/DCT
;   bytes, and the boot slot/drive at $B7E9/$B7EA are identical to the 8-bit
;   client (verified against Beneath Apple DOS) - do NOT change them.
TOKBUF     = $9000     ; sector buffer (the free $9000-$95FF gap above the code)
RWTS       = $BD00     ; DOS 3.3 RWTS entry (A=lo/Y=hi -> IOB)
TOKTRK     = $12       ; reserved token track
TOKSEC     = $0F       ; reserved token sector

; ---- scrollback ring buffer (bank $02): each line = 80 cells of (char,color) ----
BUF_BANK   = $02
BUF_LINES  = 128
BUF_STRIDE = 160       ; 80 cells * 2 bytes
CELL_BULLET = $01      ; stored-char value meaning "the reply bullet glyph"
SCROLL_STEP = 3        ; lines moved per arrow press

; set curcol/currow/txtcolor/strptr and draw a string
.macro TEXT lbl, col, row, colr
        rep     #$20
        .a16
        lda     #col
        sta     curcol
        lda     #row
        sta     currow
        lda     #lbl
        sta     strptr
        sep     #$20
        .a8
        lda     #colr
        sta     txtcolor
        jsr     draw_str
.endmacro

.a8
.i8
start:
        sei
        clc
        xce
        rep     #$30
        .a16
        .i16
        ldx     #$01FF
        txs
        sep     #$20
        .a8
        lda     #$E1
        sta     destptr+2
        stz     rb_head         ; ring buffer is used during the splash
        stz     rb_tail         ; (vbl_edge polls) - init before anything serial
        stz     menusel
        stz     quitflag
        stz     mus_on
        stz     mus_rel
        stz     mus_relv
        stz     wake_done

        lda     #$C1
        sta     NEWVIDEO
        lda     BORDERCOL
        and     #$F0
        sta     BORDERCOL

        ; SCBs = $80 (640 mode)
        rep     #$30
        .a16
        lda     #$8080
        ldx     #$0000
@sc:    sta     f:$E19D00,x
        inx
        inx
        cpx     #200
        bne     @sc
        ; palette
        ldx     #$0000
@pc:    lda     shr_palette,x
        sta     f:$E19E00,x
        inx
        inx
        cpx     #32
        bne     @pc
        jsr     clear_screen

        ; ---- splash: Clawd-does-his-laptop-act while the modem dials ----
        ; splash palette: entry 1 = the sprite's shadow coral (restored at
        ; teardown, where entry 1 goes back to the UI gray)
        rep     #$30
        .a16
        .i16
        ldx     #0
@spal:  lda     shr_palette_splash,x
        sta     f:$E19E00,x
        inx
        inx
        cpx     #32
        bne     @spal
        sep     #$20
        .a8
        sep     #$10
        .i8
        lda     #0
        jsr     splash_frame

        jsr     scc_init        ; real hardware: the port is dead until programmed
        lda     BORDERCOL
        and     #$F0
        ora     #$0F            ; DEBUG breadcrumb: WHITE border = SCC programmed
        sta     BORDERCOL
        and     #$F0            ; (dialing now happens from the menu)
        sta     BORDERCOL
        jsr     snd_init        ; DOC: load the waveform, oscillators halted

        TEXT    str_welcome, 22, 16, 2
        TEXT    str_ver, 28, 17, 3
        TEXT    str_by, 31, 18, 3

; =====================================================================
; boot menu - the act loops above it forever, keys work immediately.
; anim_ix/anim_cd walk splash_seq (frame, vblanks, ..., $FF wraps).
; The whole boot phase runs the splash palette (shadow coral + platinum);
; the session palette loads at Connect.
; =====================================================================
menu_screen:
        .a8
        .i8
        jsr     clear_screen
        TEXT    str_welcome, 22, 16, 2
        TEXT    str_ver, 28, 17, 3
        TEXT    str_by, 31, 18, 3
        lda     wake_done       ; the wake gesture greets the FIRST menu
        bne     mw_no           ; only - revisits are silent (W-488)
        inc     wake_done
        jsr     snd_wake
mw_no:
        stz     anim_ix
        lda     #1
        sta     anim_cd
menu_loop:
        jsr     menu_draw
mk_wait:
        jsr     rb_poll
        lda     KBD
        bmi     mk_key
        jsr     vbl_edge        ; one ~60Hz tick paces the animation
        jsr     music_tick      ; ...and the music
        dec     anim_cd
        bne     mk_wait
        ldx     anim_ix         ; countdown done: next storyboard entry
        lda     splash_seq,x
        cmp     #$FF
        bne     ma_go
        stz     anim_ix         ; act over: rest on the dedicated hold frame
        lda     #SPLASH_HOLD    ;   (stand pose, arms 1px taller on the bottom)
        jsr     splash_frame
        lda     #60             ;   ...for ~1s, then the act loops
        sta     anim_cd
        bra     mk_wait
ma_go:
        phx
        jsr     splash_frame
        plx
        inx
        lda     splash_seq,x
        sta     anim_cd
        inx
        stx     anim_ix
        bra     mk_wait
mk_key:
        sta     KBDSTRB
        and     #$7F
        cmp     #$0B            ; up arrow
        beq     mk_up
        cmp     #$0A            ; down arrow
        beq     mk_dn
        cmp     #$0D            ; Return
        beq     mk_go
        cmp     #'1'
        bcc     mk_wait
        cmp     #'5'
        bcs     mk_wait
        sec
        sbc     #'1'
        sta     menusel         ; digit = select and run
        bra     mk_go
mk_up:
        lda     menusel
        beq     mk_wait
        dec     menusel
        jmp     menu_loop
mk_dn:
        lda     menusel
        cmp     #3
        bcs     mk_wait
        inc     menusel
        jmp     menu_loop
mk_go:
        lda     menusel
        beq     act_connect
        cmp     #1
        beq     mk_modem
        cmp     #2
        beq     mk_instr
        jmp     act_quit
mk_modem:
        jsr     music_stop
        jmp     page_modem
mk_instr:
        jsr     music_stop
        jmp     page_instr

; connect: wipe the menu, dial, spin for ~3s, then the session
act_connect:
        jsr     music_stop
        ; Still online from the last session? Only DCD can say - and only
        ; if the pin has ever read "no carrier" (dcd_trust), which proves
        ; it's a live signal and not strapped. KEGS and a modem that
        ; doesn't drive DCD never earn trust, so they dial every time,
        ; exactly as before.
        lda     #$10            ; WR0 Reset Ext/Status -> RR0 tracks the pin
        sta     SCC_STAT
        lda     SCC_STAT        ; RR0
        and     #$08            ; DCD
        beq     ac_nocar
        lda     dcd_trust
        beq     ac_dial
        lda     rb_head         ; carrier's still up: skip the redial,
        sta     rb_tail         ; straight into the session
        jmp     session_start
ac_nocar:
        lda     #1              ; the pin can go low, so a high means a carrier
        sta     dcd_trust
ac_dial:
        lda     rb_head         ; drop stale rx from a previous session
        sta     rb_tail
        lda     #20
        jsr     clear_rowA
        lda     #21
        jsr     clear_rowA
        lda     #22
        jsr     clear_rowA
        lda     #23
        jsr     clear_rowA
        TEXT    str_dial, 36, 21, 2
        stz     dialres
        stz     mdm_c1
        lda     #2
        sta     dcol            ; dial-echo column on row 22
        jsr     modem_dial
        jsr     snd_dialt       ; the dial-up theater plays under the window
        ldx     #30             ; 30 beats of 6 vblanks = ~3s
ac_lp:
        phx
        txa
        and     #$03
        tax
        lda     dial_glyphs,x
        pha
        rep     #$20
        .a16
        lda     #34
        sta     curcol
        lda     #21
        sta     currow
        sep     #$20
        .a8
        lda     #2
        sta     txtcolor
        pla
        jsr     putchar
        ldy     #6
ac_w:   jsr     vbl_edge
        jsr     music_tick
        dey
        bne     ac_w
ac_rx:  jsr     havebyte        ; classify any modem chatter from this beat
        beq     ac_ck
        jsr     getbyte
        pha
        jsr     dial_byte
        pla
        jsr     dial_echo       ; ...and show it: a failed dial should
        bra     ac_rx           ; leave evidence on the screen
ac_ck:  plx
        lda     dialres
        cmp     #1              ; CONNECT -> settled; let the theater end
        beq     ac_hold
        cmp     #2              ; ERROR/BUSY/NO x -> say so, back to menu
        beq     ac_fail
        dex
        bne     ac_lp
        ; 3s of silence = no modem in the path (KEGS) or already online:
        ; proceed - through the same ring-out as a fast CONNECT
        ; A fast modem answers mid-theater; a buzz chopped at half a note
        ; reads as a glitch, not carrier detect (W-517). The verdict is in,
        ; so stop classifying - just drain rx and let the stream finish.
ac_hold:
        lda     mus_on
        beq     ac_sess
        jsr     vbl_edge
        jsr     music_tick
ac_hrx: jsr     havebyte
        beq     ac_hold
        jsr     getbyte
        jsr     dial_echo
        bra     ac_hrx
ac_sess:
        jsr     music_stop      ; the stream just ended; halt the oscillators
        jmp     session_start
ac_fail:
        jsr     music_stop
        lda     #21
        jsr     clear_rowA
        TEXT    str_dfail, 21, 21, 2
        ldy     #200            ; leave it up ~3.3s, then back to the menu
af_w:   jsr     vbl_edge
        dey
        bne     af_w
        jmp     menu_screen

; menu_draw - the four items at rows 16-19, selected one coral with '>'
menu_draw:
        .a8
        .i8
        ldx     #0
md_lp:
        phx
        txa
        clc
        adc     #20
        pha
        jsr     clear_rowA
        pla
        rep     #$20
        .a16
        and     #$00FF
        sta     currow
        lda     #30
        sta     curcol
        sep     #$20
        .a8
        plx
        phx
        txa
        asl     a
        tay
        rep     #$20
        .a16
        lda     menu_ptrs,y
        sta     strptr
        sep     #$20
        .a8
        plx
        phx
        cpx     menusel
        beq     md_sel
        lda     #3              ; gray (platinum), no marker
        sta     txtcolor
        lda     #' '
        jsr     putchar
        lda     #' '
        jsr     putchar
        bra     md_txt
md_sel:
        lda     #2              ; coral with the '>' marker
        sta     txtcolor
        lda     #'>'
        jsr     putchar
        lda     #' '
        jsr     putchar
md_txt:
        jsr     draw_str
        plx
        inx
        cpx     #4
        bne     md_lp
        rts

; =====================================================================
; modem page - a live Hayes AT console. Keys go straight to the modem
; (it echoes them back, E1), replies print in the window. Esc = menu.
; =====================================================================
page_modem:
        jsr     clear_screen
        TEXT    str_mdm_t, 34, 2, 2
        TEXT    str_mdm_1, 4, 4, 3
        TEXT    str_mdm_2, 4, 5, 3
        TEXT    str_mdm_3, 4, 6, 3
        TEXT    str_mdm_4, 24, 22, 3
        rep     #$20
        .a16
        lda     #0
        sta     curcol
        lda     #8
        sta     currow
        sep     #$20
        .a8
mp_loop:
        jsr     havebyte
        beq     mp_key
        jsr     getbyte
        and     #$7F
        cmp     #$0D
        beq     mp_nl
        cmp     #$20
        bcc     mp_loop
        cmp     #$7F
        bcs     mp_loop
        pha
        lda     #3              ; modem traffic in platinum
        sta     txtcolor
        pla
        jsr     mp_put
        bra     mp_loop
mp_nl:
        jsr     mp_newline
        bra     mp_loop
mp_key:
        lda     KBD
        bpl     mp_loop
        sta     KBDSTRB
        and     #$7F
        cmp     #$1B            ; Esc -> back to the menu
        beq     mp_done
        cmp     #$0D
        beq     mp_send
        cmp     #$20
        bcc     mp_loop
        cmp     #$7F
        bcs     mp_loop
        jsr     sccput
        bra     mp_loop
mp_send:
        lda     #$0D
        jsr     sccput
        bra     mp_loop
mp_done:
        jmp     menu_screen

; mp_put/mp_newline - echo window plumbing (rows 8-20, wraps, clears)
mp_put:
        .a8
        .i8
        pha
        rep     #$20
        .a16
        lda     curcol
        cmp     #80
        sep     #$20
        .a8
        bcc     mp_ok
        jsr     mp_newline
mp_ok:
        pla
        jmp     putchar
mp_newline:
        .a8
        .i8
        rep     #$20
        .a16
        lda     #0
        sta     curcol
        lda     currow
        inc     a
        cmp     #21
        bcc     mp_nl2
        lda     #8
mp_nl2: sta     currow
        sep     #$20
        .a8
        lda     currow          ; low byte; blank the row we are entering
        jsr     clear_rowA
        rts

; instructions page
page_instr:
        jsr     clear_screen
        TEXT    str_ins_t, 28, 1, 2
        TEXT    str_ins_1, 4, 3, 3
        TEXT    str_ins_b0, 4, 5, 2
        TEXT    str_ins_b1, 4, 6, 3
        TEXT    str_ins_b2, 4, 7, 3
        TEXT    str_ins_b3, 4, 8, 3
        TEXT    str_ins_m0, 4, 10, 2
        TEXT    str_ins_m1, 4, 11, 3
        TEXT    str_ins_m2, 4, 12, 3
        TEXT    str_ins_m3, 4, 13, 3
        TEXT    str_ins_s0, 4, 15, 2
        TEXT    str_ins_s1, 4, 16, 3
        TEXT    str_ins_u1, 4, 18, 3
        TEXT    str_ins_u2, 4, 19, 3
        TEXT    str_anykey, 28, 22, 3
        jsr     page_key
        jmp     menu_screen
page_key:
        .a8
        .i8
pk_w:   jsr     rb_poll
        lda     KBD
        bpl     pk_w
        sta     KBDSTRB
        rts

; quit: back to text mode and pull the reset cord (lands at BASIC)
act_quit:
        sep     #$30
        .a8
        .i8
        jsr     music_stop
        lda     #$01
        sta     NEWVIDEO        ; SHR off, classic video
        sec
        xce                     ; emulation mode
        lda     $C051           ; text on
        lda     $C054           ; page 1
        jmp     ($03F2)         ; warm reset -> ProDOS/BASIC

session_start:
        rep     #$30            ; session palette: real gray and white
        .a16
        .i16
        ldx     #0
@sspal: lda     shr_palette,x
        sta     f:$E19E00,x
        inx
        inx
        cpx     #32
        bne     @sspal
        sep     #$10
        .i8
        sep     #$20
        .a8
        ; ---- session screen ----
        jsr     clear_screen
        rep     #$20
        .a16
        lda     #(SHR_BASE + 6*160 + 2)     ; mascot's home in the header
        sta     mascot_at
        sep     #$20
        .a8
        jsr     draw_mascot
        .a8

        TEXT    str_title, 12, 1, 2     ; placeholder until the bridge's header lands

        ; transcript cursor starts below the header
        rep     #$20
        .a16
        lda     #0
        sta     curcol
        lda     #START_ROW
        sta     currow
        sep     #$20
        .a8
        lda     #$FF            ; first spinner advance -> word 0 (Cogitating)
        sta     spinword
        ; scrollback buffer
        stz     b_head
        lda     #1
        sta     b_count         ; line 0 exists (empty)
        stz     b_col
        stz     b_view
        stz     header_locked
        lda     #BUF_BANK
        sta     bufptr+2
        jsr     buf_setline     ; bufptr -> line 0
        jsr     buf_clearline
        lda     BORDERCOL
        and     #$F0
        ora     #$0D            ; DEBUG breadcrumb: YELLOW border = init complete
        sta     BORDERCOL

        lda     #$10            ; sample DCD now: high = a real carrier, so
        sta     SCC_STAT        ; gate future sends on it dropping; low =
        lda     SCC_STAT        ; don't gate (KEGS / a modem without DCD)
        and     #$08
        sta     dcd_active

        ; auto-pair vs. bare probe. Do the RWTS token read FIRST, while the
        ; bridge is still SILENT (require_pairing pushes nothing until it reads
        ; a line from us). If we probed first, the bridge's synchronous
        ; LOCKED-header reply would land during the ~100-200ms deaf RWTS read
        ; and the SCC's 3-byte FIFO would drop it on real hardware - the user
        ; would never see the prompt. token_read returns its result in carry and
        ; tok_valid in Z; sccput/lda both CLOBBER those flags, so we consume them
        ; to pick the branch BEFORE any transmit, and each case sends once.
        ; The token helpers exit .a16/.i16 (they rep #$30 before rts).
        jsr     tok_init_dev
        .a16
        .i16
        jsr     token_read
        bcs     st_probe        ; RWTS read failed (write-protected/no disk)
        jsr     tok_valid
        bne     st_probe        ; no/invalid token on disk: bare probe
        ; valid token: present it as the FIRST line the bridge reads, so a
        ; paired device skips the code prompt. The bridge answers with EOT +
        ; the real header - no separate bare-CR probe needed.
        sep     #$30
        .a8
        .i8
        ldx     #0
st_snd: cpx     TOKBUF+6        ; +6 = stored token length
        beq     st_sndcr
        lda     TOKBUF+7,x      ; token bytes live at +7..
        jsr     sccput          ; sccput preserves X
        inx
        bra     st_snd          ; len < 40, so X never wraps
st_sndcr:
        lda     #$0D
        jsr     sccput
        bra     st_afterprobe
st_probe:
        sep     #$30            ; arrived here .a16/.i16 (token helper exit)
        .a8
        .i8
        lda     #$0D            ; session-open probe: the bridge answers with the
        jsr     sccput          ; LOCKED header (fresh/errored/unpaired disk)
st_afterprobe:

; =====================================================================
; main loop
; =====================================================================
main:
        jsr     draw_box
        lda     BORDERCOL
        and     #$F0            ; DEBUG breadcrumb: black border = UI fully up
        sta     BORDERCOL
        jsr     read_line
        lda     quitflag        ; Ctrl-C while idle = /quit
        beq     mn_live
        jmp     quit_to_menu
mn_live:
        lda     linelen
        beq     main
        jsr     draw_box        ; clear typed text from the input box on Enter
        ; /quit and /exit are handled locally and BEFORE any transmit -
        ; otherwise the line hits the wire, and with no carrier the modem
        ; (in command mode) interprets it (Wells saw "/quit" land on the
        ; WiModem).
        lda     linelen
        cmp     #5
        bne     mn_notq
        ldx     #4
mn_qck: lda     linebuf,x
        ora     #$20            ; case-fold ('/' has bit 5 set already)
        cmp     str_quit,x
        bne     mn_exck
        dex
        bpl     mn_qck
        jmp     quit_to_menu
mn_exck:
        ldx     #4
mn_eck: lda     linebuf,x
        ora     #$20
        cmp     str_exit,x
        bne     mn_notq
        dex
        bpl     mn_eck
        jmp     quit_to_menu
mn_notq:
        jsr     echo_user
        jsr     check_carrier   ; don't spray text at a modem in command mode
        bcs     mn_spin
        jsr     say_nocarr      ; carrier gone -> note it, drop to the menu
        ldx     #120
mn_npz: jsr     vbl_edge
        dex
        bne     mn_npz
        jmp     quit_to_menu
mn_spin:
        jsr     send_line
        jsr     spinner
        jsr     recv_reply
        jsr     token_flush     ; deferred token write, now that the bridge is idle
        jsr     bell_maybe      ; BEL semantics: ring once after a long think
        lda     quitflag        ; bridge sent CMD_QUIT during this reply?
        beq     main
; /quit acknowledged: restore the boot palette and rejoin the menu. The
; menu re-entry is the same one the AT console uses; Connect redials.
quit_to_menu:
        stz     quitflag
        lda     rb_head         ; drop buffered rx (a live bridge's goodbye
        sta     rb_tail         ; bytes shouldn't leak into the next session)
        rep     #$30
        .a16
        .i16
        ldx     #0
qm_pal: lda     shr_palette_splash,x
        sta     f:$E19E00,x
        inx
        inx
        cpx     #32
        bne     qm_pal
        sep     #$30
        .a8
        .i8
        jmp     menu_screen

; =====================================================================
; draw_box - rules at RULE1/RULE2, "> " at INPUT_ROW, clear input line
; =====================================================================
draw_box:
        .a8
        .i8
        lda     #RULE1_ROW
        jsr     draw_rule
        lda     #RULE2_ROW
        jsr     draw_rule
        lda     #INPUT_ROW
        jsr     clear_rowA
        ; draw "> " prompt (gray) at col0 INPUT_ROW, preserving transcript cursor
        rep     #$20
        .a16
        lda     curcol
        pha
        lda     currow
        pha
        lda     #0
        sta     curcol
        lda     #INPUT_ROW
        sta     currow
        lda     #str_prompt
        sta     strptr
        sep     #$20
        .a8
        lda     #1
        sta     txtcolor
        jsr     draw_str
        rep     #$20
        .a16
        pla
        sta     currow
        pla
        sta     curcol
        sep     #$20
        .a8
        rts

; =====================================================================
; read_line - read keys into linebuf, echo at INPUT_ROW, return on CR.
;   preserves transcript cursor (curcol/currow).
; =====================================================================
read_line:
        .a8
        .i8
        ; save transcript cursor
        rep     #$20
        .a16
        lda     curcol
        sta     savecol
        lda     currow
        sta     saverow
        ; input cursor at col2/INPUT_ROW
        lda     #2
        sta     curcol
        lda     #INPUT_ROW
        sta     currow
        sep     #$20
        .a8
        lda     #1
        sta     txtcolor
        stz     linelen
rl_key:
        lda     KBD
        bmi     rl_haskey       ; bit7 set -> a key is waiting
        jsr     check_incoming  ; else pick up a header frame the bridge sent
        bra     rl_key
rl_haskey:
        sta     KBDSTRB         ; clear strobe (consume this key)
        and     #$7F
        cmp     #$0B            ; up arrow -> scroll back
        beq     rl_up
        cmp     #$0A            ; down arrow -> scroll forward (toward live)
        beq     rl_down
        cmp     #$0D            ; CR
        beq     rl_cr
        cmp     #$08            ; backspace (left-arrow)
        beq     rl_bs
        cmp     #$7F            ; DEL key -> also backspace
        beq     rl_bs
        cmp     #$03            ; Ctrl-C while idle = /quit
        beq     rl_cc
        cmp     #$20            ; below space -> ignore
        bcc     rl_key
        cmp     #$7F
        bcs     rl_key
        ; printable
        pha
        jsr     snap_live_input ; leave scrollback if we were paged up
        pla
        ldx     linelen
        cpx     #76
        bcs     rl_key          ; full
        sta     linebuf,x
        inc     linelen
        jsr     putchar         ; echo (advances curcol)
        bra     rl_key
rl_up:
        lda     linelen
        bne     rl_key          ; only page when the input line is empty
        jsr     scroll_back
        jsr     restore_input_cursor
        bra     rl_key
rl_down:
        lda     linelen
        bne     rl_key
        jsr     scroll_fwd
        jsr     restore_input_cursor
        bra     rl_key
rl_cr:
        jsr     snap_live_input
        bra     rl_done
rl_bs:
        lda     linelen
        beq     rl_key
        dec     linelen
        ; erase: curcol--, draw space, curcol--
        rep     #$20
        .a16
        dec     curcol
        sep     #$20
        .a8
        lda     #' '
        jsr     putchar
        rep     #$20
        .a16
        dec     curcol
        sep     #$20
        .a8
        bra     rl_key
rl_cc:  lda     #1              ; flag it; main routes to quit_to_menu
        sta     quitflag        ; (a jmp from here would leak stack)
        stz     linelen
rl_done:
        ; null-terminate linebuf
        ldx     linelen
        lda     #0
        sta     linebuf,x
        ; restore transcript cursor
        rep     #$20
        .a16
        lda     savecol
        sta     curcol
        lda     saverow
        sta     currow
        sep     #$20
        .a8
        rts

; =====================================================================
; echo_user - print "> " + linebuf + newline into the transcript
; =====================================================================
echo_user:
        .a8
        .i8
        lda     #3              ; white: user's submitted messages
        sta     txtcolor
        lda     #'>'
        jsr     cout
        lda     #' '
        jsr     cout
        ldx     #0
eu_lp:  lda     linebuf,x
        beq     eu_done
        phx
        jsr     cout
        plx
        inx
        bne     eu_lp
eu_done:
        lda     #$0D
        jsr     cout
        lda     #$0D            ; blank line between message and reply
        jsr     cout
        rts

; =====================================================================
; send_line - transmit linebuf + CR over the SCC
; =====================================================================
send_line:
        .a8
        .i8
        ldx     #0
sl_lp:  lda     linebuf,x
        beq     sl_cr
        jsr     sccput
        inx
        bne     sl_lp
sl_cr:  lda     #$0D
        jsr     sccput
        rts

; check_carrier - carry SET = ok to transmit. Only gates when DCD was
; asserted at session start (dcd_active): a modem that doesn't drive
; DCD, or KEGS, is never blocked, but a real carrier that later drops
; is caught before we spray text at a modem back in command mode.
; RR0 bit3 = DCD; rb_poll leaves the SCC register pointer at 0.
check_carrier:
        .a8
        .i8
        lda     dcd_active
        beq     cc_ok
        lda     #$10            ; WR0 Reset Ext/Status -> RR0 tracks the pin
        sta     SCC_STAT
        lda     SCC_STAT        ; RR0
        and     #$08            ; DCD
        beq     cc_no
cc_ok:  sec
        rts
cc_no:  clc
        rts

; say_nocarr - note the dropped carrier in the transcript (coral)
say_nocarr:
        .a8
        .i8
        lda     #2
        sta     txtcolor
        ldx     #0
sc_lp:  lda     str_nocarr,x
        beq     sc_d
        phx
        jsr     cout
        plx
        inx
        bne     sc_lp
sc_d:   lda     #$0D
        jsr     cout
        rts

; =====================================================================
; clear_screen - all SHR pixels to black. Callable from any M/X width.
; =====================================================================
clear_screen:
        php
        rep     #$30
        .a16
        .i16
        lda     #$0000
        ldx     #$0000
cs_lp:  sta     f:$E12000,x
        inx
        inx
        cpx     #$7D00
        bne     cs_lp
        plp
        rts

; =====================================================================
; scc_init - program SCC channel B (modem port) for 9600 8N1, polled.
;   A real IIgs only hardware-resets the SCC at power-on; the channel moves
;   no bytes until clocks are set and Rx/Tx enabled (Apple IIgs TN #018).
;   KEGS ignores most of this but accepts the writes. Interrupts must be
;   off around the pointer/value write pairs (they are: sei at start, no cli).
; =====================================================================
SCC_BAUD_TC = 10        ; 3686400/(2*16*baud)-2: 10 = 9600, 4 = 19200
scc_init:
        .a8
        .i8
        lda     SCC_STAT        ; force the WR0 register pointer to a known state
        ldx     #0
si_lp:  lda     scc_tab,x       ; register number -> WR0
        sta     SCC_STAT
        inx
        lda     scc_tab,x       ; value -> that register
        sta     SCC_STAT
        inx
        cpx     #scc_tab_end-scc_tab
        bne     si_lp
        rts

scc_tab:
        .byte   9,  $40         ; channel B reset
        .byte   4,  $44         ; x16 clock, 1 stop bit, no parity
        .byte   3,  $C0         ; Rx 8 bits/char, receiver still off
        .byte   5,  $EA         ; Tx 8 bits, Tx enable, RTS + DTR asserted
        .byte   11, $50         ; Rx and Tx clock = baud rate generator
        .byte   12, SCC_BAUD_TC ; BRG time constant, low byte
        .byte   13, $00         ; BRG time constant, high byte
        .byte   14, $01         ; BRG enable, source = RTxC (3.6864 MHz)
        .byte   15, $00         ; no external/status interrupts
        .byte   1,  $00         ; no Rx/Tx interrupts (polled)
        .byte   9,  $00         ; master interrupt enable off
        .byte   3,  $C1         ; receiver on
scc_tab_end:

; =====================================================================
; bell_maybe - one period bell when a reply lands after a >=15s think
; (the spinner's second counter runs until the first reply byte). BEL
; semantics: a notification for a user who's looked away, not decoration.
; Blocks ~0.6s while the tone rings down; the ring buffer stays serviced.
bell_maybe:
        .a8
        .i8
        lda     quitflag        ; session's over: leave quietly
        bne     bm_x
        lda     sp_huns
        bne     bm_ring
        lda     sp_tens
        cmp     #2
        bcs     bm_ring
        cmp     #1
        bne     bm_x
        lda     sp_ones
        cmp     #5
        bcc     bm_x
bm_ring:
        jsr     snd_bell
bm_lp:  jsr     rb_poll
        jsr     vbl_edge
        jsr     music_tick
        lda     mus_on
        bne     bm_lp
bm_x:   rts

; modem_dial - unconditionally send "ATDS=0" CR (dial phone book entry 0).
;   No connected-check: a probe can't work, because in command mode the
;   modem ECHOES the probe byte and the echo is indistinguishable from an
;   answer. Instead: command mode -> the modem dials; already online ->
;   the string reaches the bridge, which recognizes ATD... lines and
;   swallows them. CONNECT/OK chatter is ignored as stray bytes.
; =====================================================================
modem_dial:
        .a8
        .i8
        lda     #$0D            ; flush half-typed junk on the modem first -
        jsr     sccput          ;   "foo" + our dial would send fooATDS=0
        ldy     #15             ; ~250ms for the modem to answer the flush
md_fl:  jsr     vbl_edge
        dey
        bne     md_fl
        lda     rb_head         ; drop that answer (ERROR/OK, don't care)
        sta     rb_tail
        ldx     #0
md_snd: lda     dial_str,x
        beq     md_cr
        jsr     sccput          ; sccput preserves X
        inx
        bne     md_snd
md_cr:  lda     #$0D
        jsr     sccput
        rts

; dial_echo - print the modem's responses on row 22 during the dial,
; gray, one line at a time (CR clears the row). Diagnosis beats a
; spinner when a dial goes sideways in the field.
dial_echo:
        .a8
        .i8
        and     #$7F
        cmp     #$0D
        beq     @nl
        cmp     #$20
        bcc     @x
        cmp     #$7F
        bcs     @x
        ldx     dcol
        cpx     #78
        bcs     @x              ; clip long lines at the right edge
        pha
        rep     #$20            ; own cursor: the beat spinner moves the
        .a16                    ; shared one every ~100ms
        lda     #0
        sta     curcol
        lda     #22
        sta     currow
        sep     #$20
        .a8
        lda     dcol
        rep     #$20
        .a16
        and     #$00FF
        sta     curcol
        sep     #$20
        .a8
        lda     #1              ; gray
        sta     txtcolor
        pla
        jsr     putchar
        inc     dcol
        rts
@nl:    lda     #22
        jsr     clear_rowA
        lda     #2
        sta     dcol
@x:     rts

; dial_byte - classify modem response lines during the dial window, one
; rx byte at a time. First letter E(RROR)/B(USY) or "NO.." = fail,
; "CO.." (CONNECT) = success; "OK"/"RING"/anything else is ignored.
; Sets dialres: 1 = connect, 2 = fail. Silence leaves it 0.
dial_byte:
        .a8
        .i8
        and     #$7F
        cmp     #$0D
        beq     db_nl
        cmp     #$20
        bcc     db_x            ; other control bytes: ignore
        ldx     mdm_c1
        bne     db_c2
        sta     mdm_c1          ; first printable of the line
        cmp     #'E'
        beq     db_fail
        cmp     #'B'
        beq     db_fail
        rts
db_c2:  cpx     #$FF            ; line already classified/consumed
        beq     db_x
        pha
        lda     #$FF            ; consume the rest of the line either way
        sta     mdm_c1
        pla
        cmp     #'O'            ; second char must be O for CONNECT / NO x
        bne     db_x
        cpx     #'C'
        beq     db_conn
        cpx     #'N'
        beq     db_fail
        rts
db_conn:
        lda     #1
        sta     dialres
        rts
db_fail:
        lda     #2
        sta     dialres
db_nl:  stz     mdm_c1
db_x:   rts

dial_str:
        .byte   "ATDS=0",0

spin_glyphs:
        .byte   "*+:+"          ; pulse cycle for the thinking spinner

; =====================================================================
; splash_frame - A (a8) = frame index. Draws one frame of the clawd.gif
;   port, tripled: each stored 2-bit pixel becomes 3 screen bytes (12px)
;   wide and 6 scanlines tall, via the expand4_n solid-byte tables.
;   splash_data/splash_off/splash_seq all come from assets.inc (generated
;   from the gif itself). Uses zp srcp/srcrow. a8/i8 in and out.
;   Invariant inside the pixel loop: B (A's hidden high byte) = 0, so TAX
;   in 8-bit A yields a clean 16-bit table index.
; =====================================================================
SPLASH_XOFF = (160 - 8*SPLASH_BYTES)/2
SPLASH_TOP  = 18
splash_frame:
        .a8
        .i8
        pha
        rep     #$30
        .a16
        .i16
        lda     #(SHR_BASE + SPLASH_TOP*160 + SPLASH_XOFF)
        sta     destptr
        sep     #$20
        .a8
        lda     #SPLASH_H
        sta     rowcnt
        pla                     ; frame index
        rep     #$30
        .a16
        .i16
        and     #$00FF
        asl     a
        tax
        lda     splash_off,x
        clc
        adc     #splash_data    ; srcp -> this frame's first byte
        sta     srcp
        lda     #$0000          ; B := 0 for the TAX trick
        sep     #$20
        .a8
sf_row:
        rep     #$20
        .a16
        lda     srcp            ; remember the row start; it is drawn 3 times
        sta     srcrow
        lda     #$0000
        sep     #$20
        .a8
        lda     #3
        sta     rowrep
sf_rep:
        rep     #$20
        .a16
        lda     srcrow
        sta     srcp
        lda     #$0000
        sep     #$20
        .a8
        ldy     #0
sf_byte:
        lda     (srcp)          ; one stored byte = 4 source pixels
        tax                     ; (B=0 -> clean index)
        lda     expand4_0,x     ; each pixel becomes 2 solid bytes (8 px)
        sta     [destptr],y
        iny
        sta     [destptr],y
        iny
        lda     expand4_1,x
        sta     [destptr],y
        iny
        sta     [destptr],y
        iny
        lda     expand4_2,x
        sta     [destptr],y
        iny
        sta     [destptr],y
        iny
        lda     expand4_3,x
        sta     [destptr],y
        iny
        sta     [destptr],y
        iny
        inc     srcp
        bne     sfb_n
        inc     srcp+1
sfb_n:  cpy     #8*SPLASH_BYTES
        bne     sf_byte
        rep     #$20
        .a16
        lda     destptr
        clc
        adc     #160
        sta     destptr
        lda     #$0000
        sep     #$20
        .a8
        dec     rowrep
        bne     sf_rep
        dec     rowcnt
        bne     sf_row
        sep     #$10
        .i8
        rts

; sccput - send A over SCC, waiting for the Tx buffer to empty first (required
;   on real hardware; KEGS would accept immediately). Preserves X.
sccput:
        pha
scp_wait:
        lda     SCC_STAT        ; RR0 bit2 = Tx buffer empty
        and     #$04
        beq     scp_wait
        pla
        sta     SCC_DATA
        rts

; =====================================================================
; serial Rx ring buffer - the SCC FIFO is only 3 bytes deep, so anything
; slow (scroll_up, clear_rowA, waiting on vblank) must keep draining the
; port or bytes are lost. rb_poll stashes into RBUF from inside those
; loops; every reader goes through getbyte/havebyte, buffered bytes first.
; This is why the bridge needs no --pace-cps for this client.
; =====================================================================
; rb_poll - drain the SCC FIFO into RBUF. Callable from ANY M/X width;
;   preserves X/Y, trashes A. The drain is BOUNDED (FIFO is 3 deep) and ends
;   with a WR0 Error Reset: a real 8530 latches Rx overrun - guaranteed at
;   boot while the modem's dial echo arrives during UI drawing - and a wedged
;   status bit would spin an unbounded drain loop forever. KEGS models none
;   of this, so only real hardware hangs without the bound + reset.
rb_poll:
        php
        rep     #$30
        .a16
        .i16
        phx
        phy
        sep     #$30
        .a8
        .i8
        ldy     #4              ; more than the FIFO holds; hard upper bound
rp_lp:  lda     SCC_STAT
        and     #$01
        beq     rp_x
        lda     SCC_DATA
        ldx     rb_head
        sta     RBUF,x
        inx                     ; 8-bit index wraps at 256 naturally
        stx     rb_head
        dey
        bne     rp_lp
rp_x:   lda     #$30            ; WR0 = Error Reset: clear latched overrun
        sta     SCC_STAT
        rep     #$30
        .a16
        .i16
        ply
        plx
        plp
        rts

; getbyte - next serial byte -> A (blocking). Buffered bytes first. Preserves X.
getbyte:
        .a8
        .i8
        phx
gb_lp:  ldx     rb_tail
        cpx     rb_head
        bne     gb_buf
        jsr     rb_poll         ; sole SCC reader: bounded drain + error reset
        bra     gb_lp
gb_buf: lda     RBUF,x
        inx
        stx     rb_tail
        plx
        rts

; havebyte - A=1/BNE if a byte is waiting, A=0/BEQ if not. Preserves X.
havebyte:
        .a8
        .i8
        phx
        jsr     rb_poll
        ldx     rb_tail
        cpx     rb_head
        beq     hb_no
        lda     #1
        bra     hb_x
hb_no:  lda     #0
hb_x:   plx
        cmp     #0              ; plx clobbered Z; re-derive it from A
        rts

; =====================================================================
; spinner - animate until a byte is available (min frames for visibility)
; =====================================================================
spinner:
        .a8
        .i8
        stz     frame
        stz     havefirst
        stz     sp_vblsub
        stz     sp_ones
        stz     sp_tens
        stz     sp_huns
        inc     spinword        ; next word for this reply
        lda     spinword
        cmp     #SPIN_COUNT
        bcc     @wc
        stz     spinword
@wc:
        lda     #5              ; seconds until the word rotates
        sta     sp_wordcd
sp_lp:
        lda     KBD             ; Esc aborts the wait - escape hatch when the
        bpl     sp_nk           ; link is dead and no reply will ever come
        sta     KBDSTRB
        and     #$7F
        cmp     #$1B
        beq     sp_esc
        cmp     #$03            ; Ctrl-C: ask the bridge to stop the turn
        bne     sp_nk
        lda     #$03            ; a bare byte on the wire; the bridge kills
        jsr     sccput          ; the claude turn and EOTs what it has
        bra     sp_nk
sp_esc: lda     #1
        sta     quitflag
        lda     #EOT            ; fake end-of-reply: recv_reply finishes
        bra     sp_exj          ; instantly, main sees quitflag -> menu
sp_nk:
        jsr     havebyte
        beq     sp_draw         ; no byte -> keep spinning
        ; a byte is waiting: consume it, discard leading control bytes so the
        ; spinner stays up until the reply's first real character arrives
        jsr     getbyte
        and     #$7F
        cmp     #EOT
        beq     sp_exj          ; empty reply -> stash EOT and stop
        cmp     #CMD_COLOR      ; color/bullet/header markers are real content
        beq     sp_exj
        cmp     #CMD_BULLET
        beq     sp_exj
        cmp     #CMD_HEADER
        beq     sp_exj
        cmp     #CMD_TOKEN      ; token frame can be the first byte back (issued
        beq     sp_exj          ; right after a good code) - keep it for recv_reply
        cmp     #CMD_QUIT
        beq     sp_q            ; session over: latch it, keep draining to EOT
        cmp     #$20
        bcc     sp_lp           ; CR/LF/NUL before reply -> discard, keep spinning
        cmp     #$7F
        bcs     sp_lp           ; stray high byte -> discard
sp_exj: brl     sp_exit         ; first printable char in A (sp_exit is far now)
sp_q:   lda     #1
        sta     quitflag
        bra     sp_lp
sp_draw:
        lda     #2              ; coral word
        sta     txtcolor
        rep     #$20
        .a16
        lda     #0
        sta     curcol
        sep     #$20
        .a8
        ; animated star: pulse * + : + like the real TUI spinner
        lda     frame
        lsr     a
        and     #$03
        tax
        lda     spin_glyphs,x
        jsr     putchar
        ; word: strptr = spin_ptrs[spinword]
        lda     spinword
        asl     a               ; *2 (2-byte pointers)
        tax
        rep     #$20
        .a16
        lda     spin_ptrs,x
        sta     strptr
        sep     #$20
        .a8
        jsr     draw_str        ; " Word..."
        ; elapsed timer in gray:  (Ns)
        lda     #1
        sta     txtcolor
        lda     #' '
        jsr     putchar
        lda     #'('
        jsr     putchar
        jsr     draw_secs
        lda     #'s'
        jsr     putchar
        lda     #')'
        jsr     putchar
        ; pad to col 30 with spaces to erase a longer previous render
sp_pad:
        rep     #$20
        .a16
        lda     curcol
        cmp     #30
        sep     #$20
        .a8
        bcs     sp_paced
        lda     #' '
        jsr     putchar
        bra     sp_pad
sp_paced:
        jsr     spin_pace       ; ~100ms real-time; advances the timer
        inc     frame
        brl     sp_lp           ; long branch: sp_lp is >127 bytes back
sp_exit:
        sta     firstbyte       ; A = first real byte (or EOT)
        lda     #1
        sta     havefirst
        rep     #$20
        .a16
        lda     currow
        sep     #$20
        .a8
        jsr     clear_rowA      ; wipe " COGITATING..." line
        rep     #$20
        .a16
        lda     #0
        sta     curcol
        sep     #$20
        .a8
        rts

; =====================================================================
; spin_pace - ~100ms of real-time pacing (6 vblanks) while advancing the
;   elapsed-second counters; bails early if a reply byte is ready.
; =====================================================================
spin_pace:
        .a8
        .i8
        ldx     #6
sp_pc:
        jsr     havebyte
        bne     sp_pc_x         ; byte ready -> stop pacing, sp_lp handles it
        jsr     vbl_edge        ; one vblank (~1/60s)
        inc     sp_vblsub
        lda     sp_vblsub
        cmp     #60
        bcc     sp_pc_n
        stz     sp_vblsub
        jsr     tick_second
sp_pc_n:
        dex
        bne     sp_pc
sp_pc_x:
        rts

; tick_second - one elapsed second: bump the decimal digit counters and, every
;   sp_wordcd seconds, rotate to the next thinking word.
tick_second:
        .a8
        .i8
        inc     sp_ones
        lda     sp_ones
        cmp     #10
        bcc     ts_word
        stz     sp_ones
        inc     sp_tens
        lda     sp_tens
        cmp     #10
        bcc     ts_word
        stz     sp_tens
        inc     sp_huns
ts_word:
        dec     sp_wordcd
        bne     ts_done
        inc     spinword
        lda     spinword
        cmp     #SPIN_COUNT
        bcc     ts_cd
        stz     spinword
ts_cd:
        lda     #5
        sta     sp_wordcd
ts_done:
        rts

; draw_secs - print the elapsed seconds (sp_huns/tens/ones) with no leading zeros
draw_secs:
        .a8
        .i8
        lda     sp_huns
        beq     ds_tens
        clc
        adc     #'0'
        jsr     putchar
        lda     sp_tens         ; huns shown -> always show tens
        clc
        adc     #'0'
        jsr     putchar
        bra     ds_ones
ds_tens:
        lda     sp_tens
        beq     ds_ones
        clc
        adc     #'0'
        jsr     putchar
ds_ones:
        lda     sp_ones
        clc
        adc     #'0'
        jsr     putchar
        rts

; vbl_edge - wait for one 0->1 transition of RDVBL bit7 (~1/60s, real time).
;   Each phase is bounded (~50ms) so a non-toggling emulator degrades to a fast
;   timer instead of a frozen client. Preserves X (spin_pace's loop counter).
vbl_edge:
        .a8
        .i8
        phx
        rep     #$10
        .i16
        ldx     #$8000
ve1:    jsr     rb_poll         ; stay deaf to the port for no more than one pass
        lda     RDVBL
        bpl     ve1b            ; bit7 = 0 -> proceed to wait for the rising edge
        dex
        bne     ve1
        bra     ve_x            ; timed out
ve1b:
        ldx     #$8000
ve2:    jsr     rb_poll
        lda     RDVBL
        bmi     ve_x            ; bit7 = 1 -> 0->1 edge seen
        dex
        bne     ve2
ve_x:
        sep     #$10
        .i8
        plx
        rts

; =====================================================================
; recv_reply - read bytes until EOT, cout each (skip LF)
; =====================================================================
recv_reply:
        .a8
        .i8
        lda     #1              ; replies default to gray
        sta     txtcolor
        stz     colorpend
        stz     muteflag
        lda     havefirst       ; spinner already pulled the first real byte
        beq     rr_next
        lda     firstbyte
        bra     rr_disp
rr_next:
        lda     KBD             ; Ctrl-C mid-printout: stop drawing, but
        bpl     rr_gb           ; keep draining to EOT (the reply is
        sta     KBDSTRB         ; already fully sent - only display stops)
        and     #$7F
        cmp     #$03
        bne     rr_gb
        lda     #1
        sta     muteflag
rr_gb:
        jsr     getbyte
        and     #$7F
rr_disp:
        ldx     colorpend       ; awaiting a color value byte?
        beq     rr_nocp
        sta     txtcolor
        stz     colorpend
        bra     rr_next
rr_nocp:
        cmp     #EOT
        beq     rr_done
        cmp     #CMD_COLOR      ; 0x01 -> next byte is a color
        beq     rr_setcp
        cmp     #CMD_BULLET     ; 0x02 -> draw white reply bullet
        beq     rr_bullet
        cmp     #CMD_HEADER     ; 0x0E -> header frame (title CR subtitle CR)
        beq     rr_header
        cmp     #CMD_TOKEN      ; 0x05 -> capture + persist a freshly issued token
        beq     rr_token
        cmp     #CMD_QUIT       ; 0x03 -> session over after this reply
        beq     rr_quit
        cmp     #$0A            ; skip LF
        beq     rr_next
        ldx     muteflag        ; muted: consume, draw nothing
        bne     rr_next
        jsr     cout
        bra     rr_next
rr_quit:
        lda     #1
        sta     quitflag
        bra     rr_next
rr_setcp:
        lda     #1
        sta     colorpend
        bra     rr_next
rr_bullet:
        lda     muteflag
        bne     rr_next
        jsr     draw_bullet
        bra     rr_next
rr_header:
        jsr     do_header
        bra     rr_next
rr_token:
        jsr     do_token        ; capture + persist a freshly issued token
        .a16                    ; do_token exits .a16/.i16 (token_write reps)
        .i16
        sep     #$30            ; back to recv_reply's 8-bit
        .a8
        .i8
        bra     rr_next
rr_done:
        lda     #$0D
        jsr     cout
        lda     #$0D            ; blank line before the next message
        jsr     cout
        rts

; =====================================================================
; do_header - a CMD_HEADER frame arrived: two CR-terminated lines (real title
;   then subtitle). Draw them once at the fixed header slot (rows 1-3, col 12);
;   on later frames just consume the bytes. Preserves the transcript cursor.
; =====================================================================
do_header:
        .a8
        .i8
        lda     header_locked
        beq     dh_draw
        jsr     hdr_skipline    ; header frozen (scrolled off) -> discard the frame
        jsr     hdr_skipline
        jsr     hdr_skipline
        rts
dh_draw:
        rep     #$20            ; save cursor (transcript or input)
        .a16
        lda     curcol
        sta     hsavecol
        lda     currow
        sta     hsaverow
        lda     #12             ; title at row 1, col 12
        sta     curcol
        lda     #1
        sta     currow
        sep     #$20
        .a8
        lda     #2              ; coral
        sta     txtcolor
        jsr     hdr_readline
        rep     #$20            ; subtitle at row 2
        .a16
        lda     #12
        sta     curcol
        lda     #2
        sta     currow
        sep     #$20
        .a8
        lda     #1              ; gray
        sta     txtcolor
        jsr     hdr_readline
        rep     #$20            ; working directory at row 3
        .a16
        lda     #12
        sta     curcol
        lda     #3
        sta     currow
        sep     #$20
        .a8
        lda     #1              ; gray
        sta     txtcolor
        jsr     hdr_readline
        rep     #$20            ; restore cursor
        .a16
        lda     hsavecol
        sta     curcol
        lda     hsaverow
        sta     currow
        sep     #$20
        .a8
        lda     #1
        sta     txtcolor
        rts

; hdr_readline - draw printable bytes from the SCC until CR, then pad to col 40
;   with spaces so a shorter update overwrites the previous header text.
hdr_readline:
        .a8
        .i8
hrl_lp:
        jsr     getbyte
        and     #$7F
        cmp     #$0D
        beq     hrl_pad
        cmp     #$20
        bcc     hrl_lp
        cmp     #$7F
        bcs     hrl_lp
        jsr     putchar
        bra     hrl_lp
hrl_pad:
        rep     #$20
        .a16
        lda     curcol
        cmp     #56
        sep     #$20
        .a8
        bcs     hrl_x
        lda     #' '
        jsr     putchar
        bra     hrl_pad
hrl_x:
        rts

; hdr_skipline - read and discard SCC bytes until CR
hdr_skipline:
        .a8
        .i8
hsk_lp:
        jsr     getbyte
        and     #$7F
        cmp     #$0D
        bne     hsk_lp
        rts

; check_incoming - non-blocking: draw a header frame the bridge sent while idle
;   (so the real header appears at boot). Ignores any other stray byte.
check_incoming:
        .a8
        .i8
        jsr     havebyte
        beq     ci_x
        jsr     getbyte
        and     #$7F
        cmp     #CMD_HEADER
        bne     ci_x
        jsr     do_header
ci_x:
        rts

; =====================================================================
; token sector I/O - RWTS-read/write a reserved sector (T=$12 S=$0F) on the
; boot disk to persist a device-pairing token across reboots. RWTS is a
; monolithic 8-bit DOS routine (6502 opcodes; it never runs rep/sep, so M/X
; stay 8-bit across it) - we enter these helpers in native 8-bit mode
; (sep #$30) and rep #$30 back to the client's 16-bit convention before rts,
; per the 65816 width rule. The only unavoidably-deaf stretch is inside RWTS
; itself, which can't be woven with rb_poll - see the report caveat.
; Sector layout: magic "CLDTK1"(6) | len(1) | token(len) | csum(1).
; csum = 8-bit sum (mod 256) of bytes [0 .. 6+len]. Byte-identical to the
; 8-bit client so a token is portable between clients.
; =====================================================================

; Copy the boot slot/drive out of DOS's own primary IOB ($B7E9/$B7EA) so token
; I/O targets the same physical device the client booted from. Exits .a16/.i16.
tok_init_dev:
        sep     #$30
        .a8
        .i8
        lda     $B7E9           ; DOS boot slot (slot*16)
        sta     iob_slot
        lda     $B7EA           ; DOS boot drive
        sta     iob_drive
        rep     #$30
        .a16
        .i16
        rts

; RWTS-read the token sector into TOKBUF. Carry clear = success. Exits .a16/.i16.
token_read:
        sep     #$30
        .a8
        .i8
        lda     #TOKTRK
        sta     iob_trk
        lda     #TOKSEC
        sta     iob_sec
        lda     #$01            ; command 1 = read
        sta     iob_cmd
        bra     rwts_call

; RWTS-write TOKBUF to the token sector. Carry clear = success. Exits .a16/.i16.
token_write:
        sep     #$30
        .a8
        .i8
        lda     #TOKTRK
        sta     iob_trk
        lda     #TOKSEC
        sta     iob_sec
        lda     #$02            ; command 2 = write
        sta     iob_cmd
        ; fall through (still .a8/.i8)
rwts_call:
        lda     #<iob
        ldy     #>iob           ; A=lo/Y=hi -> IOB, per DOS 3.3 RWTS
        jsr     RWTS            ; 6502 code: returns with M/X still 8-bit
        lda     iob_err         ; Z=1 if ok (0 = no error)
        rep     #$30            ; rep preserves Z from the lda above
        .a16
        .i16
        beq     rc_ok
        sec
        rts
rc_ok:  clc
        rts

; tok_valid - after token_read, returns Z=1 (A=0) if TOKBUF holds valid magic
; and a matching checksum; Z=0 (A=1) otherwise. Uses $06 scratch. Exits .a16/.i16.
tok_valid:
        sep     #$30
        .a8
        .i8
        ldx     #0
tv_m:   lda     TOKBUF,x
        cmp     tok_magic,x
        bne     tv_bad
        inx
        cpx     #6
        bne     tv_m
        lda     TOKBUF+6        ; len
        beq     tv_bad          ; len 0 = invalid
        cmp     #$29            ; > 40 ($28) = corrupt over-read; bound it
        bcs     tv_bad          ; (do_token caps writes at 40)
        sta     $06             ; scratch (known-safe ZP; = tmp2, dead here)
        lda     #0
        ldx     #0
tv_s:   clc
        adc     TOKBUF,x        ; sum magic+len: indices 0..6
        inx
        cpx     #7
        bcc     tv_s
        ldy     #0
tv_t:   cpy     $06             ; summed all len token bytes?
        beq     tv_done
        clc
        adc     TOKBUF+7,y      ; sum token: indices 7..6+len
        iny
        bne     tv_t
tv_done:
        ldy     $06
        cmp     TOKBUF+7,y      ; compare to checksum byte at index 7+len
        bne     tv_bad
        lda     #0              ; Z=1: valid
        bra     tv_exit
tv_bad: lda     #1              ; Z=0: invalid
tv_exit:
        rep     #$30            ; rep preserves Z from the lda above
        .a16
        .i16
        rts

; do_token - a CMD_TOKEN frame is arriving: read the CR-terminated token, frame
; it into TOKBUF in the on-disk layout, and RWTS-write it. getbyte polls rb_poll
; so the ring can't overflow while we read. Exits .a16/.i16.
do_token:
        sep     #$30
        .a8
        .i8
        ldx     #0
dt_wm:  lda     tok_magic,x     ; stamp the magic
        sta     TOKBUF,x
        inx
        cpx     #6
        bne     dt_wm
        ldx     #0
dt_rt:  jsr     getbyte         ; getbyte enters/exits .a8/.i8
        and     #$7F
        cmp     #$0D
        beq     dt_fin
        sta     TOKBUF+7,x
        inx
        cpx     #$28            ; hard cap 40 (token is 32) - never overrun
        bcc     dt_rt
dt_fin: stx     TOKBUF+6        ; length
        lda     #0
        ldy     #0
dt_ck1: clc
        adc     TOKBUF,y        ; sum magic+len: indices 0..6
        iny
        cpy     #7
        bcc     dt_ck1
        ldy     #0
dt_ck2: cpy     TOKBUF+6
        beq     dt_ckd
        clc
        adc     TOKBUF+7,y      ; sum token: indices 7..6+len
        iny
        bne     dt_ck2
dt_ckd: ldy     TOKBUF+6
        sta     TOKBUF+7,y      ; store checksum at index 7+len
        lda     #1              ; DEFER the RWTS write: doing it here (inside
        sta     token_pending   ; recv_reply) would go deaf ~150ms and drop the
                                ; trailing EOT. token_flush writes it at idle.
        rep     #$30            ; restore do_token's .a16/.i16 exit contract
        .a16
        .i16
        rts

; token_flush - perform the deferred token write. Called from the main loop
; right after recv_reply, when the bridge is silent (waiting for the user's
; next line), so the RWTS deaf window can't eat any serial. Enters .a8/.i8 and
; MUST exit .a8/.i8 for the code after it; token_write does its own sep/rep and
; returns .a16/.i16, so we sep back down before returning.
token_flush:
        lda     token_pending
        beq     tf_done         ; nothing pending: return .a8/.i8, width untouched
        jsr     token_write     ; RWTS write; ignore carry; returns .a16/.i16
        .a16
        .i16
        sep     #$30            ; back to the caller's .a8/.i8
        .a8
        .i8
        stz     token_pending
tf_done:
        rts

tok_magic:  .byte   "CLDTK1"

; DOS 3.3 RWTS IOB (17 bytes) + DCT. Slot/drive are patched from DOS's own
; boot IOB by tok_init_dev. Layout per Beneath Apple DOS ch.6. This is data -
; control never falls into it (do_token rts's above).
iob:        .byte   $01         ; +0  IOB type ($01)
iob_slot:   .byte   $60         ; +1  slot*16 (patched at boot)
iob_drive:  .byte   $01         ; +2  drive (patched at boot)
iob_vol:    .byte   $00         ; +3  volume expected (0 = any)
iob_trk:    .byte   TOKTRK      ; +4  track
iob_sec:    .byte   TOKSEC      ; +5  sector
            .word   dct         ; +6  DCT pointer
            .word   TOKBUF      ; +8  data buffer
            .word   $0000       ; +10 unused
iob_cmd:    .byte   $01         ; +12 command 1=read 2=write
iob_err:    .byte   $00         ; +13 error code (return)
            .byte   $00         ; +14 last volume (return)
            .byte   $60         ; +15 last slot (return)
            .byte   $01         ; +16 last drive (return)
dct:        .byte   $00,$01,$EF,$D8  ; device characteristics table

; =====================================================================
; cout - print A with cursor handling; CR = newline+scroll
; =====================================================================
cout:
        .a8
        .i8
        cmp     #$0D
        beq     co_nl
        cmp     #$20
        bcc     co_ret          ; control char -> ignore
        cmp     #$7F
        bcs     co_ret          ; >=127 -> ignore
        pha
        jsr     putchar         ; advances curcol
        pla
        jsr     rec_cell        ; record into the scrollback buffer
        rep     #$20
        .a16
        lda     curcol
        cmp     #80
        sep     #$20
        .a8
        bcc     co_ret          ; still room
        ; wrap
co_nl:
        jsr     buf_newline     ; advance the scrollback ring to a new line
        rep     #$20
        .a16
        lda     #0
        sta     curcol
        inc     currow
        lda     currow
        cmp     #(BOT_ROW+1)
        sep     #$20
        .a8
        bcc     co_ret
        ; past bottom -> scroll, currow = BOT_ROW
        jsr     scroll_up
        rep     #$20
        .a16
        lda     #BOT_ROW
        sta     currow
        sep     #$20
        .a8
co_ret:
        rts

; =====================================================================
; scroll_up - move transcript region up one text row, clear bottom
; =====================================================================
scroll_up:
        .a8
        .i8
        lda     #1              ; header has now scrolled off -> freeze it
        sta     header_locked
        ; copy rows TOP_ROW+1..BOT_ROW up one row, in bank $E1, as 16-bit words.
        ; (mvn block-move corrupted KEGS' emulated state; a plain [dp],y copy is
        ;  the same mechanism putchar/clear_rowA already use safely.)
        lda     #$E1
        sta     srcptr+2
        sta     destptr+2
        rep     #$30
        .a16
        .i16
        lda     #((TOP_ROW+1)*1280 + SHR_BASE)
        sta     srcptr
        lda     #(TOP_ROW*1280 + SHR_BASE)
        sta     destptr
        ldy     #0
scu_lp:
        tya                     ; drain the port every 256 bytes moved
        and     #$00FF
        bne     scu_cp
        jsr     rb_poll
scu_cp:
        lda     [srcptr],y
        sta     [destptr],y
        iny
        iny
        cpy     #((BOT_ROW-TOP_ROW)*1280)
        bne     scu_lp
        sep     #$20
        .a8
        sep     #$10
        .i8
        lda     #BOT_ROW
        jsr     clear_rowA
        rts

; =====================================================================
; clear_rowA - clear 8 scanlines (1280 bytes) of text row A to black
; =====================================================================
clear_rowA:
        .a8
        .i8
        ; destptr = SHR_BASE + row*1280  ((row*5)<<8)
        rep     #$20
        .a16
        and     #$00FF
        sta     tmp2
        asl     a
        asl     a
        clc
        adc     tmp2            ; row*5
        xba                     ; *256 -> row*1280
        clc
        adc     #SHR_BASE
        sta     destptr
        sep     #$20
        .a8
        rep     #$10
        .i16
        ldy     #0
cra_lp:
        tya                     ; low byte of Y; drain the port every 256 bytes
        bne     cra_st
        jsr     rb_poll
cra_st: lda     #0
        sta     [destptr],y
        iny
        cpy     #1280
        bne     cra_lp
        sep     #$10
        .i8
        rts

; =====================================================================
; draw_mascot - the single static mascot frame (deliberately not animated)
; =====================================================================
; callable from any A/X width (boot calls in a16); exits .a8/.i8.
draw_mascot:
        rep     #$30
        .a16
        .i16
        lda     mascot_at       ; header slot normally; the splash centers it
        sta     destptr
        sep     #$20
        .a8
        lda     #MASCOT_H
        sta     rowcnt
        ldx     #0              ; data offset within mascot_data
dm_row:
        ldy     #$0000
dm_byte:
        lda     mascot_data,x
        sta     [destptr],y
        inx
        iny
        cpy     #MASCOT_BYTES
        bne     dm_byte
        rep     #$20
        .a16
        lda     destptr
        clc
        adc     #160
        sta     destptr
        sep     #$20
        .a8
        dec     rowcnt
        bne     dm_row
        sep     #$10
        .i8
        rts

; =====================================================================
; draw_str - draw null string at curcol/currow in txtcolor
; =====================================================================
draw_str:
        .a8
        .i8
        ldy     #0
ds_loop:
        lda     (strptr),y
        beq     ds_done
        phy
        jsr     putchar
        ply
        iny
        bne     ds_loop
ds_done:
        rts

; =====================================================================
; putchar - draw glyph A at curcol/currow, advance curcol
; =====================================================================
putchar:
        .a8
        .i8
        rep     #$20
        .a16
        and     #$00FF
        sec
        sbc     #FONT_FIRST
        asl     a
        asl     a
        asl     a
        clc
        adc     #font_data
        sta     glyphptr
put_common:                     ; entry with glyphptr preset, still .a16
        lda     currow
        asl     a
        asl     a
        clc
        adc     currow          ; row*5
        xba                     ; *256
        sta     tmp
        lda     curcol
        asl     a
        clc
        adc     tmp
        clc
        adc     #SHR_BASE
        sta     destptr
        sep     #$20
        .a8
        lda     txtcolor
        asl     a
        asl     a
        asl     a
        asl     a
        sta     coloff
        ldx     #8
pc_row:
        ldy     #0
        lda     (glyphptr),y
        pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     coloff
        tay
        lda     expand_tbl,y
        ldy     #0
        sta     [destptr],y
        pla
        and     #$0F
        clc
        adc     coloff
        tay
        lda     expand_tbl,y
        ldy     #1
        sta     [destptr],y
        rep     #$20
        .a16
        inc     glyphptr
        lda     destptr
        clc
        adc     #160
        sta     destptr
        sep     #$20
        .a8
        dex
        bne     pc_row
        inc     curcol
        rts

; =====================================================================
; draw_bullet - draw the white reply bullet at curcol/currow (advances curcol),
;   then restore gray so the reply body stays gray.
; =====================================================================
draw_bullet:
        .a8
        .i8
        lda     #3              ; white
        sta     txtcolor
        rep     #$20
        .a16
        lda     #bullet_data
        sta     glyphptr
        jsr     put_common      ; draw + advance curcol (returns in .a8)
        .a8                     ; put_common left the accumulator 8-bit
        lda     #CELL_BULLET    ; record bullet cell (color still white)
        jsr     rec_cell
        lda     #1              ; restore gray for the reply body
        sta     txtcolor
        rts

; =====================================================================
; scrollback buffer helpers (ring of lines in bank BUF_BANK)
; =====================================================================
; bufptr(low) = b_head * BUF_STRIDE
buf_setline:
        .a8
        .i8
        lda     b_head
; A = line index -> bufptr(low) = A * 160
buf_setline_a:
        .a8
        .i8
        rep     #$20
        .a16
        and     #$00FF
        sta     tmp
        asl     a
        asl     a               ; *4
        clc
        adc     tmp             ; *5
        asl     a
        asl     a
        asl     a
        asl     a
        asl     a               ; *32 -> *160
        sta     bufptr
        sep     #$20
        .a8
        rts

; fill the line at bufptr with (space, gray) cells
buf_clearline:
        .a8
        .i8
        ldy     #0
bcl_lp:
        lda     #$20
        sta     [bufptr],y
        iny
        lda     #1
        sta     [bufptr],y
        iny
        cpy     #BUF_STRIDE
        bne     bcl_lp
        rts

; rec_cell - store char A (+txtcolor) at the current line, column b_col; advance
rec_cell:
        .a8
        .i8
        pha
        lda     b_col
        cmp     #80
        bcs     rc_full
        asl     a               ; b_col * 2
        tay
        pla
        sta     [bufptr],y      ; char
        iny
        lda     txtcolor
        sta     [bufptr],y      ; color
        inc     b_col
        rts
rc_full:
        pla
        rts

; buf_newline - commit the current line, advance the ring to a fresh blank line
buf_newline:
        .a8
        .i8
        lda     b_col           ; finalize this line's content length
        ldx     b_head
        sta     b_len,x
        inc     b_head
        lda     b_head
        cmp     #BUF_LINES
        bcc     bn_1
        stz     b_head
bn_1:
        lda     b_count
        cmp     #BUF_LINES
        bcs     bn_2
        inc     b_count
bn_2:
        stz     b_col
        jsr     buf_setline
        jsr     buf_clearline
        rts

; =====================================================================
; draw_view - redraw rows 0..BOT_ROW from the ring at scrollback offset b_view.
;   Row R shows the line (BOT_ROW - R + b_view) back from the head. Only used
;   once the screen has scrolled (b_count > 21), so the live layout is always
;   bottom-anchored and matches this mapping.
; =====================================================================
draw_view:
        .a8
        .i8
        stz     dv_r
dv_row:
        lda     #BOT_ROW        ; delta = BOT_ROW - dv_r + b_view
        sec
        sbc     dv_r
        clc
        adc     b_view
        cmp     b_count
        bcc     dv_draw         ; delta < b_count -> a recorded line exists
        lda     dv_r            ; before the oldest line -> blank row
        jsr     clear_rowA
        bra     dv_next
dv_draw:
        sta     vdelta
        lda     b_head
        sec
        sbc     vdelta
        bcs     dv_nw
        clc
        adc     #BUF_LINES      ; wrap into the ring
dv_nw:
        sta     vln
        jsr     draw_buf_line
dv_next:
        inc     dv_r
        lda     dv_r
        cmp     #(BOT_ROW+1)
        bne     dv_row
        rts

; draw_buf_line - draw buffer line `vln` into screen row `dv_r`. Draws only the
;   recorded content cells, then fast-clears the rest of the row.
draw_buf_line:
        .a8
        .i8
        rep     #$20
        .a16
        lda     #0
        sta     curcol
        lda     dv_r
        and     #$00FF
        sta     currow
        sep     #$20
        .a8
        ; content length: the live head line uses b_col, others use b_len[]
        lda     vln
        cmp     b_head
        bne     @stored
        lda     b_col
        bra     @havelen
@stored:
        ldx     vln
        lda     b_len,x
@havelen:
        sta     dvlen
        lda     vln
        jsr     buf_setline_a
        ldx     #0
dbl_lp:
        cpx     dvlen
        bcs     dbl_done
        txa
        asl     a               ; cell*2
        tay
        lda     [bufptr],y      ; char
        pha
        iny
        lda     [bufptr],y      ; color
        sta     txtcolor
        pla
        phx
        jsr     draw_cell
        plx
        inx
        bra     dbl_lp
dbl_done:
        jsr     clear_row_tail  ; blank the remaining cells fast
        rts

; clear_row_tail - zero the SHR bytes for cells curcol..79 of row currow
clear_row_tail:
        .a8
        .i8
        rep     #$20
        .a16
        lda     currow
        and     #$00FF
        sta     tmp2
        asl     a
        asl     a
        clc
        adc     tmp2            ; row*5
        xba                     ; *256 -> row*1280
        clc
        adc     #SHR_BASE
        sta     destptr
        lda     curcol
        asl     a               ; start byte = curcol*2
        sta     tmp2
        sep     #$20
        .a8
        lda     #8
        sta     rowcnt
crt_sl:
        rep     #$30
        .a16
        .i16
        ldy     tmp2
        lda     #0
crt_by:
        cpy     #160
        bcs     crt_slend
        sta     [destptr],y
        iny
        iny
        bra     crt_by
crt_slend:
        clc
        lda     destptr
        adc     #160
        sta     destptr
        sep     #$30
        .a8
        .i8
        dec     rowcnt
        bne     crt_sl
        rts

; draw_cell - draw stored char A at curcol/currow (bullet glyph if CELL_BULLET)
draw_cell:
        .a8
        .i8
        cmp     #CELL_BULLET
        beq     dc_bullet
        jmp     putchar
dc_bullet:
        rep     #$20
        .a16
        lda     #bullet_data
        sta     glyphptr
        jmp     put_common

; scroll_back / scroll_fwd / live_if_scrolled - move the scrollback view
scroll_back:
        .a8
        .i8
        lda     b_count
        cmp     #(BOT_ROW+2)    ; <= 21 lines -> nothing scrolled off yet
        bcc     sb_x
        sec
        sbc     #(BOT_ROW+1)    ; maxview = b_count - 21
        sta     tmp2            ; maxview
        lda     b_view
        clc
        adc     #SCROLL_STEP    ; new view = view + step, clamped to maxview
        cmp     tmp2
        bcc     sb_set
        lda     tmp2
sb_set:
        cmp     b_view
        beq     sb_x            ; already at the top
        sta     b_view
        jsr     draw_view
sb_x:
        rts

scroll_fwd:
        .a8
        .i8
        lda     b_view
        beq     sf_x            ; already live
        sec
        sbc     #SCROLL_STEP    ; new view = view - step, clamped to 0
        bcs     sf_set
        lda     #0
sf_set:
        sta     b_view
        jsr     draw_view
sf_x:
        rts

live_if_scrolled:
        .a8
        .i8
        lda     b_view
        beq     lis_x
        stz     b_view
        jsr     draw_view
lis_x:
        rts

; restore_input_cursor - put the cursor back in the input box (col 2, empty line)
;   and reset the color (draw_view left txtcolor at the last cell's color).
restore_input_cursor:
        .a8
        .i8
        rep     #$20
        .a16
        lda     #2
        sta     curcol
        lda     #INPUT_ROW
        sta     currow
        sep     #$20
        .a8
        lda     #1              ; input echoes in gray
        sta     txtcolor
        rts

; snap_live_input - if scrolled back, jump to live and reset the input cursor
snap_live_input:
        .a8
        .i8
        lda     b_view
        beq     sli_x
        jsr     live_if_scrolled
        jsr     restore_input_cursor
sli_x:
        rts

; =====================================================================
; draw_rule - draw a gray horizontal line across text row A
; =====================================================================
draw_rule:
        .a8
        .i8
        ; scanline = row*8 + 4 ; destptr = SHR_BASE + scanline*160 ((s*5)<<5)
        rep     #$20
        .a16
        and     #$00FF
        asl     a
        asl     a
        asl     a               ; row*8
        clc
        adc     #4              ; scanline
        sta     tmp2
        asl     a
        asl     a
        clc
        adc     tmp2            ; s*5
        asl     a
        asl     a
        asl     a
        asl     a
        asl     a               ; *32 -> s*160
        clc
        adc     #SHR_BASE
        sta     destptr
        sep     #$20
        .a8
        ldy     #0
        lda     #$55            ; four gray pixels
dr_lp:
        sta     [destptr],y
        iny
        cpy     #160
        bne     dr_lp
        rts

; =====================================================================
; delay - crude busy wait (spinner pacing)
; =====================================================================
delay:
        .a8
        .i8
        phx
        phy
        ldx     #$00
dl1:    ldy     #$00
dl2:    iny
        bne     dl2
        inx
        cpx     #$60
        bne     dl1
        ply
        plx
        rts

; =====================================================================
; menu music - two DOC oscillators driven from the menu's 60Hz VBL tick.
; The ditty (streams in assets.inc: freq_lo, freq_hi, dur_vblanks
; triplets; freq 0 = rest) plays ONCE per menu visit; the dur-0
; terminator stops it. All DOC access goes through the Sound GLU
; ($C03C ctrl / $C03D data / $C03E-F address). Never write a $00
; sample: it halts the oscillator.
; =====================================================================
MUS_VOL0 = $1A          ; melody oscillator volume (~10% - per Wells on metal)
MUS_VOL1 = $11          ; bass oscillator volume
GLU_CTRL = $C03C
GLU_DATA = $C03D
GLU_ALO  = $C03E
GLU_AHI  = $C03F

; glu_wait - the real Sound GLU raises bit7 (busy) around DOC cycles;
; accesses made while it's set are lost. KEGS doesn't model this, so
; "plays in KEGS" proves nothing (the SCC lesson, sound edition).
glu_wait:
        .a8
        pha
gw_lp:  lda     GLU_CTRL
        bmi     gw_lp
        pla
        rts

; doc_wr - write A to DOC register X
doc_wr:
        .a8
        .i8
        pha
        jsr     glu_wait
        lda     #$08            ; ctrl: DOC registers, no autoinc, volume 8
        sta     GLU_CTRL
        stx     GLU_ALO
        stz     GLU_AHI
        jsr     glu_wait
        pla
        sta     GLU_DATA
        rts

; snd_init - waveform into sound RAM page 0; two oscillators set up, halted
snd_init:
        .a8
        .i8
        jsr     glu_wait
        lda     #$68            ; ctrl: sound RAM + autoincrement + volume 8
        sta     GLU_CTRL
        stz     GLU_ALO
        stz     GLU_AHI
        ldx     #0
si_wv:  jsr     glu_wait
        lda     wave_data,x
        sta     GLU_DATA        ; autoincrement walks sound RAM $0000-$00FF
        inx
        bne     si_wv
        lda     #4              ; $E1 osc enable = count*2 -> TWO oscillators
        ldx     #$E1            ; ($E1=2 enabled one: the bass never played)
        jsr     doc_wr
        lda     #0              ; wave pointers -> sound RAM page 0
        ldx     #$80
        jsr     doc_wr
        lda     #0
        ldx     #$81
        jsr     doc_wr
        lda     #0              ; wave size 256 bytes, resolution 0
        ldx     #$C0
        jsr     doc_wr
        lda     #0
        ldx     #$C1
        jsr     doc_wr
        lda     #MUS_VOL0
        ldx     #$40
        jsr     doc_wr
        lda     #MUS_VOL1
        ldx     #$41
        jsr     doc_wr
        jmp     music_stop      ; born silent: halt both oscillators

; snd_wake / snd_dialt / snd_bell - aim both voices at a stream pair and
; unhalt. A stream plays through once; music_tick handles the end: sounds
; started with mus_rel=1 get a fading release tail (the IIgs-beep decay),
; mus_rel=0 stops hard (the dial theater dies mid-buzz at CONNECT anyway).
snd_wake:
        .a8
        .i8
        rep     #$20
        .a16
        lda     #SND_WAKE0
        sta     mus_p0
        lda     #SND_WAKE1
        sta     mus_p1
        sep     #$20
        .a8
        lda     #1
        bra     snd_go
snd_bell:
        .a8
        .i8
        rep     #$20
        .a16
        lda     #SND_BELL0
        sta     mus_p0
        lda     #SND_BELL1
        sta     mus_p1
        sep     #$20
        .a8
        lda     #1
        bra     snd_go
snd_dialt:
        .a8
        .i8
        rep     #$20
        .a16
        lda     #SND_DIAL0
        sta     mus_p0
        lda     #SND_DIAL1
        sta     mus_p1
        sep     #$20
        .a8
        lda     #0
snd_go:
        sta     mus_rel
        stz     mus_relv
        lda     #MUS_VOL0       ; restore full volumes (a release ramp
        ldx     #$40            ; leaves them at the floor)
        jsr     doc_wr
        lda     #MUS_VOL1
        ldx     #$41
        jsr     doc_wr
        lda     #1              ; first tick fetches the first note
        sta     mus_cd0
        sta     mus_cd1
        lda     #1
        sta     mus_on
        lda     #0              ; unhalt: free-run, channel 0
        ldx     #$A0
        jsr     doc_wr
        lda     #0
        ldx     #$A1
        jsr     doc_wr
        rts

; music_stop - halt both oscillators (notes would sustain otherwise)
music_stop:
        .a8
        .i8
        stz     mus_on
        lda     #1              ; halt bit
        ldx     #$A0
        jsr     doc_wr
        lda     #1
        ldx     #$A1
        jsr     doc_wr
        rts

; music_tick - call once per vblank from the menu loop. Cheap: a few GLU
; writes at most, so the ring-buffer cadence is safe. Exits .a8/.i8.
music_tick:
        .a8
        .i8
        lda     mus_on
        bne     mt_on
        rts
mt_on:
        lda     mus_relv        ; ---- release tail: streams are done, the
        beq     mt_str          ; last chord rings while volume steps down
        dec     a
        sta     mus_relv
        cmp     #2
        bcc     mt_fin
        ldx     #$40
        jsr     doc_wr
        lda     mus_relv        ; voice 1 fades in step, offset by its
        sec                     ; quieter base level
        sbc     #MUS_VOL0-MUS_VOL1
        bcs     mt_rl1
        lda     #1
mt_rl1: ldx     #$41
        jsr     doc_wr
        rts
mt_fin: jmp     music_stop
mt_str:
        dec     mus_cd0         ; ---- voice 0 (osc 0)
        bne     mt_v1
        rep     #$10
        .i16
        ldx     mus_p0
        lda     music_data+2,x  ; dur 0 = stream over
        bne     mt_h0
        sep     #$10
        .i8
        lda     mus_rel         ; fade out, or fall silent right now
        beq     mt_fin
        lda     #MUS_VOL0
        sta     mus_relv
        rts
mt_h0:  lda     music_data+2,x
        sta     mus_cd0
        lda     music_data,x
        sta     mus_t0
        lda     music_data+1,x
        sta     mus_t1
        inx
        inx
        inx
        stx     mus_p0
        sep     #$10
        .i8
        lda     mus_t0
        ldx     #$00            ; osc0 freq lo/hi
        jsr     doc_wr
        lda     mus_t1
        ldx     #$20
        jsr     doc_wr
        lda     mus_t0          ; rest (freq 0) -> mute for the duration
        ora     mus_t1
        beq     mt_r0
        lda     #MUS_VOL0
        bra     mt_w0
mt_r0:  lda     #0
mt_w0:  ldx     #$40
        jsr     doc_wr
mt_v1:
        dec     mus_cd1         ; ---- voice 1 (bass, osc 1)
        bne     mt_x
        rep     #$10
        .i16
        ldx     mus_p1
        lda     music_data+2,x  ; dur 0 = this voice is done
        bne     mt_h1
        sep     #$10
        .i8
        lda     mus_rel         ; release tail: keep the chord ringing
        bne     mt_x            ; (the ramp in mt_on fades it)
        lda     #0              ; hard-stop sound: just mute this voice;
        ldx     #$41            ; voice 0 ends the stream
        jmp     doc_wr
mt_h1:  lda     music_data+2,x
        sta     mus_cd1
        lda     music_data,x
        sta     mus_t0
        lda     music_data+1,x
        sta     mus_t1
        inx
        inx
        inx
        stx     mus_p1
        sep     #$10
        .i8
        lda     mus_t0
        ldx     #$01
        jsr     doc_wr
        lda     mus_t1
        ldx     #$21
        jsr     doc_wr
        lda     mus_t0
        ora     mus_t1
        beq     mt_r1
        lda     #MUS_VOL1
        bra     mt_w1
mt_r1:  lda     #0
mt_w1:  ldx     #$41
        jsr     doc_wr
mt_x:   rts

; =====================================================================
; strings
; =====================================================================
str_title:  .byte "Claude Code",0         ; placeholder until the real header lands
str_welcome:.byte "Welcome to Terminal for Claude Code",0
str_ver:    .byte "for Apple IIgs - v1.0.1",0
str_by:     .byte "by Wells Workshop",0
str_dial:   .byte "Dialing...",0
str_dfail:  .byte "Dial failed - try the modem console",0
str_quit:   .byte "/quit"                 ; matched locally in the main loop
str_exit:   .byte "/exit"                 ; same length, same treatment
str_nocarr: .byte "* connection lost - back to menu",0
dial_glyphs:.byte "*+:-"                    ; connect spinner cycle
menu_ptrs:  .word mi0, mi1, mi2, mi3
mi0:        .byte "1. Connect",0
mi1:        .byte "2. Modem",0
mi2:        .byte "3. Instructions",0
mi3:        .byte "4. Quit to Basic",0
str_mdm_t:  .byte "MODEM CONSOLE",0
str_mdm_1:  .byte "Type Hayes AT commands; Return sends them, Esc returns to the menu.",0
str_mdm_2:  .byte "Point entry 0 at your bridge and save:  AT&Z0=BRIDGE.IP:6400  then  AT&W",0
str_mdm_3:  .byte "Connect on the menu dials  ATDS=0.  Test with  AT  (expect OK).",0
str_mdm_4:  .byte "Esc returns to the menu",0
str_ins_t:  .byte "TERMINAL FOR CLAUDE CODE",0
str_ins_1:  .byte "Talk to Claude Code from a real Apple II, over a WiFi modem.",0
str_ins_b0: .byte "THE BRIDGE (runs on a modern computer):",0
str_ins_b1: .byte "  download: github.com/wr/apple-ii-terminal-for-claude-code",0
str_ins_b2: .byte "  run:  python3 bridge.py --telnet --app --backend code",0
str_ins_b3: .byte "  it listens for your modem on TCP port 6400.",0
str_ins_m0: .byte "THE MODEM (any Hayes-compatible, e.g. WiModem232):",0
str_ins_m1: .byte "  join it to your WiFi, then store the bridge address:",0
str_ins_m2: .byte "    AT&Z0=BRIDGE.IP:6400  then  AT&W    (use the Modem console)",0
str_ins_m3: .byte "  after that, Connect dials it automatically.",0
str_ins_s0: .byte "SERIAL:",0
str_ins_s1: .byte "  IIgs modem port, 9600 8N1 - this client sets that up itself.",0
str_ins_u1: .byte "In session: /new /mode /help /quit, Ctrl-C. Arrows scroll. Ctrl-Reset quits.",0
str_ins_u2: .byte "Wells Workshop",0
str_anykey: .byte "press any key to return",0
str_model:  .byte "",0
str_link:   .byte "Apple II <-> Claude Code",0
str_prompt: .byte "> ",0

linebuf:    .res 128
sp_vblsub:  .res 1          ; vblanks counted within the current second
sp_wordcd:  .res 1          ; seconds until the thinking word rotates
sp_ones:    .res 1          ; elapsed-seconds decimal digits
sp_tens:    .res 1
sp_huns:    .res 1
b_head:     .res 1          ; ring index of the current (being-written) line
b_count:    .res 1          ; number of lines recorded (1..BUF_LINES)
b_col:      .res 1          ; column within the current line (0..79)
b_view:     .res 1          ; scrollback offset (0 = live)
header_locked: .res 1       ; nonzero once the header has scrolled off (freeze it)
rb_head:    .res 1          ; serial Rx ring buffer write index
rb_tail:    .res 1          ; serial Rx ring buffer read index
mascot_at:  .res 2          ; screen address the mascot draws at (splash centers it)
rowrep:     .res 1          ; splash draw: scanline repeat counter per stored row
menusel:    .res 1          ; boot menu: selected item 0-3
quitflag:   .res 1          ; CMD_QUIT seen: return to menu after this reply
mus_on:     .res 1          ; nonzero while a sound plays
mus_rel:    .res 1          ; 1 = this sound ends with a fading tail
mus_relv:   .res 1          ; release ramp: current volume (0 = not releasing)
wake_done:  .res 1          ; the wake gesture already greeted this boot
dialres:    .res 1          ; dial window: 0 silence, 1 CONNECT, 2 failure
dcd_active: .res 1          ; nonzero if DCD was asserted at session start
dcd_trust:  .res 1          ; DCD has read "no carrier" once: the pin is live
muteflag:   .res 1          ; Ctrl-C during recv_reply: drain without drawing
token_pending: .res 1       ; do_token framed a token: token_flush writes it at idle
mdm_c1:     .res 1          ; dial window: first char of current rx line
dcol:       .res 1          ; dial window: echo column on row 22
mus_cd0:    .res 1          ; voice 0: vblanks left on current note
mus_cd1:    .res 1          ; voice 1: vblanks left on current note
mus_t0:     .res 1          ; scratch: freq lo of the note being started
mus_t1:     .res 1          ; scratch: freq hi
mus_p0:     .res 2          ; voice 0: cursor into music_data
mus_p1:     .res 2          ; voice 1: cursor
anim_ix:    .res 1          ; menu backdrop: splash_seq cursor
anim_cd:    .res 1          ; menu backdrop: vblanks left on current frame
hsavecol:   .res 2          ; do_header: saved cursor
hsaverow:   .res 2
dv_r:       .res 1          ; draw_view: current screen row
vdelta:     .res 1          ; draw_view: lines back from head
vln:        .res 1          ; draw_view: buffer line being drawn
dvlen:      .res 1          ; draw_buf_line: content length of the line
b_len:      .res BUF_LINES  ; recorded content length of each ring line

.include "assets.inc"
