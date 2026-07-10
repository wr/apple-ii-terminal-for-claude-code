; =====================================================================
; claude2.s - text-mode client for 8-bit Apples: IIe, IIc, IIc Plus,
; and II/II+ (40-col). Plain 6502 only - no 65C02 ops - so one binary
; runs on everything. The IIgs gets the SHR client (claude.s); if this
; binary finds itself on a GS it says so and exits.
;
; Serial: 6551 ACIA at the slot-2 addresses - which is both an Apple
; Super Serial Card in slot 2 (IIe/II+) and the IIc/IIc+ built-in
; modem port (they're wired at the same soft switches). 9600 8N1.
; RX is POLLED into a page ring buffer: the 6551 buffers one byte
; (~1000 cycles of slack at 9600), so rb_poll is woven through every
; loop that could run longer - the same never-go-deaf discipline as
; the GS client. TX polls TDRE with a timeout (W65C51N never sets it).
;
; Protocol: same app-mode stream as the IIgs client. 0x01 <n> color
; (3 -> inverse, else normal), 0x02 bullet, 0x0E header frame (3 CR
; lines), 0x03 session over, 0x04 EOT.
; =====================================================================

; ---- zero page (safe under Applesoft+DOS: see CLAUDE.md landmines)
ptr     = $06           ; screen row pointer
src     = $08           ; scroll source pointer
tmp     = $FA
tmp2    = $FB
curx    = $FC
cury    = $FD
invflag = $FE           ; 0 normal, nonzero inverse

; ---- hardware
KBD     = $C000
KBDSTRB = $C010
SPKR    = $C030         ; 1-bit speaker toggle
STORE80ON  = $C001      ; write: 80STORE on (PAGE2 banks text page)
STORE80OFF = $C000      ; write
COL80ON    = $C00D      ; write
ALTCHARON  = $C00F      ; write: inverse lowercase, no flash
PAGE2OFF   = $C054      ; any access
PAGE2ON    = $C055
VBLBIT     = $C019      ; bit7 toggles with VBL (IIe/IIc; absent on II+)

ACIA_D  = $C0A8         ; SSC slot 2 == IIc/IIc+ modem port
ACIA_S  = $C0A9
ACIA_CMD = $C0AA
ACIA_CTL = $C0AB

ASAVE   = $45           ; monitor stashes A here before JMP ($3FE)
IRQVEC  = $03FE
DOSWARM = $03D0

RING    = $1F00         ; 256-byte rx ring (page below the program)

; ---- protocol
EOT        = $04
CMD_COLOR  = $01
CMD_BULLET = $02
CMD_QUIT   = $03
CMD_HEADER = $0E

; ---- layout (matches the GS client's shape)
TOPROW  = 6             ; transcript window
BTMROW  = 20
RULE1   = 21
INPUTR  = 22
RULE2   = 23
HDRCOL  = 18            ; header text, right of the mascot

; =====================================================================
; entry: identify the machine, set up screen + serial, menu
; =====================================================================
entry:
        sei
        cld
        lda     #0
        sta     quitflag
        sta     rb_head
        sta     rb_tail
        sta     invflag
        lda     #2
        sta     dly_y           ; 1MHz frame delay; IIc+ scales it up
        lda     #1
        sta     spdm            ; speaker-delay multiplier (4 on IIc+)

        ; ---- machine id (Apple II Misc TN #7)
        lda     $FBB3
        cmp     #$06
        beq     @newer
        ; $38 = Apple ][, $EA = ][+ : 40-col text path
        lda     #0
        sta     has80
        sta     hasvbl
        beq     @setw
@newer: lda     #1
        sta     hasvbl          ; provisional - probed for real below
        lda     $FBC0
        beq     @iic            ; $00 = IIc family (built-in 80 col)
        cmp     #$E0
        bne     @iie            ; $EA = unenhanced IIe
        ; enhanced IIe or IIgs: the GS id hook at $FE1F clears carry
        sec
        jsr     $FE1F
        bcc     gs_bail
@iie:   jsr     aux_test        ; IIe: 80 col only if an aux card is in
        jmp     @setw
@iic:   lda     #1
        sta     has80
        lda     $FBBF
        cmp     #$05            ; IIc Plus runs 4x - scale the delay loops
        bne     @setw
        lda     #8
        sta     dly_y
        lda     #4
        sta     spdm
@setw:
        ; does $C019 really toggle here? The IIe's VBLBAR does; the
        ; IIc's $C019 is interrupt plumbing and may sit still. Probe
        ; for ~2 frames and trust only what we see.
        lda     hasvbl
        beq     @vdone
        lda     VBLBIT
        and     #$80
        sta     tmp
        ldx     #0
        ldy     #160
@vprob: lda     VBLBIT
        and     #$80
        cmp     tmp
        bne     @vdone          ; it moves - keep hasvbl=1
        inx
        bne     @vprob
        dey
        bne     @vprob
        lda     #0              ; never moved: cycle-count instead
        sta     hasvbl
@vdone:
        lda     has80
        beq     @w40
        lda     #80
        sta     width
        sta     STORE80ON       ; 80STORE stays on for the whole run
        sta     COL80ON
        sta     ALTCHARON
        jmp     @serial
@w40:   lda     #40
        sta     width

@serial:
        ; ---- 6551: 9600 8N1, DTR on, polled (no interrupts).
        ; IRQ-driven rx died in practice: the enhanced IIe/IIc ROM
        ; interrupt dispatcher doesn't use the II+'s "A saved at $45"
        ; protocol, and a handler that assumes it corrupts the ROM's
        ; banking restore (symptom: 80STORE drops, even columns
        ; garble, eventually a crash-reboot). Polling is universal:
        ; every loop in this client calls rb_poll at least every
        ; ~600 cycles, and the byte budget at 9600 is ~1000.
        lda     #$1E
        sta     ACIA_CTL
        lda     #$0B            ; DTR on, RX IRQ disabled, RTS low
        sta     ACIA_CMD
        lda     ACIA_D          ; flush any pending byte
        cli
        jmp     menu_screen

; the GS boots this disk into the SHR client via HELLO; landing here
; means someone BRUNs COBJ8 on a GS by hand
gs_bail:
        cli
        ldx     #0
@l:     lda     str_gs,x
        beq     @done
        ora     #$80
        jsr     $FDED           ; COUT
        inx
        bne     @l
@done:  jmp     DOSWARM

; aux_test - IIe: is there memory behind the 80STORE window?
aux_test:
        sta     STORE80ON
        bit     PAGE2ON
        lda     #$42
        sta     $0400
        bit     PAGE2OFF
        lda     #$24
        sta     $0400
        bit     PAGE2ON
        lda     $0400
        cmp     #$42
        bit     PAGE2OFF
        beq     @has
        sta     STORE80OFF
        lda     #0
        sta     has80
        rts
@has:   lda     #1
        sta     has80
        rts

; rb_poll - move a waiting rx byte into the ring. THE serial read
; path: call from inside anything slow (the 6551 buffers ONE byte).
rb_poll:
        txa
        pha
        lda     ACIA_S
        and     #$08
        beq     @out
        lda     ACIA_D
        ldx     rb_head
        sta     RING,x
        inx
        stx     rb_head         ; page ring: index wraps by itself
@out:   pla
        tax
        rts

havebyte:
        jsr     rb_poll
        lda     rb_head
        cmp     rb_tail
        rts                     ; Z clear = byte waiting

getbyte:
        jsr     havebyte
        beq     getbyte
        ldx     rb_tail
        lda     RING,x
        inx
        stx     rb_tail
        rts

; aciaput - send A. Polls TDRE, but gives up after ~3ms so a W65C51N
; (TDRE never sets) still transmits at full rate.
aciaput:
        sta     tmp
        txa
        pha
        ldx     #0
@w:     lda     ACIA_S
        and     #$10
        bne     @go
        inx
        bne     @w
@go:    pla
        tax
        lda     tmp
        sta     ACIA_D
        rts

; =====================================================================
; screen primitives - direct text page writes, main/aux interleave
; =====================================================================

; putscr - A = screen code, draw at (curx,cury), advance curx
putscr:
        pha
        ldx     cury
        lda     rowlo,x
        sta     ptr
        lda     rowhi,x
        sta     ptr+1
        lda     has80
        beq     @m40
        lda     curx
        lsr                     ; y = x/2, carry = odd column
        tay
        pla
        bcs     @odd
        bit     PAGE2ON         ; even column lives in aux ram
        sta     (ptr),y
        bit     PAGE2OFF
        inc     curx
        rts
@odd:   sta     (ptr),y
        inc     curx
        rts
@m40:   ldy     curx
        pla
        sta     (ptr),y
        inc     curx
        rts

; conv - ascii in A -> screen code honoring invflag.
; Inverse is the tricky one: with ALTCHARSET on (our 80-col setup),
; screen $00-$1F = inverse upper, $20-$3F = inverse symbols, and
; $40-$5F is MOUSETEXT - so uppercase must fold $40-$5F -> $00-$1F,
; while lowercase ($60-$7F) really is inverse lowercase. Without
; ALTCHARSET (II/II+/40-col), $40-$7F would FLASH: fold lowercase
; to upper first, then everything to $00-$3F.
conv:
        ldx     invflag
        beq     @n
        ldx     has80           ; has80 == ALTCHARSET on
        bne     @alt
        cmp     #$60            ; no altchar: fold case, then to inverse
        bcc     @fold
        and     #$5F
@fold:  and     #$3F
        rts
@alt:   cmp     #$40
        bcc     @done           ; $20-$3F: already inverse symbols
        cmp     #$60
        bcs     @done           ; $60-$7F: inverse lowercase as-is
        and     #$1F            ; $40-$5F: uppercase -> $00-$1F
@done:  rts
@n:     ora     #$80
        rts

; cout - print ascii A at the transcript cursor; CR = newline; wraps
; and scrolls the TOPROW..BTMROW window
cout:
        cmp     #$0D
        beq     @nl
        cmp     #$20
        bcc     @ret            ; other control chars: ignore
        cmp     #$7F
        bcs     @ret
        jsr     conv
        jsr     putscr
        lda     curx
        cmp     width
        bcc     @ret
@nl:    lda     #0
        sta     curx
        inc     cury
        lda     cury
        cmp     #BTMROW+1
        bcc     @ret
        lda     #BTMROW
        sta     cury
        jsr     scroll_win
@ret:   rts

; scroll_win - scroll TOPROW..BTMROW up one line. rb_poll between
; every 40-byte pass: at 9600 a byte lands every ~1000 cycles.
scroll_win:
        ldx     #TOPROW
@row:   lda     rowlo,x
        sta     ptr
        lda     rowhi,x
        sta     ptr+1
        lda     rowlo+1,x
        sta     src
        lda     rowhi+1,x
        sta     src+1
        jsr     rb_poll
        lda     has80
        beq     @main
        bit     PAGE2ON
        ldy     #39
@a:     lda     (src),y
        sta     (ptr),y
        dey
        bpl     @a
        bit     PAGE2OFF
        jsr     rb_poll
@main:  ldy     #39
@b:     lda     (src),y
        sta     (ptr),y
        dey
        bpl     @b
        jsr     rb_poll
        inx
        cpx     #BTMROW
        bne     @row
        lda     #BTMROW
        ; fall through: clear row A

; clear_rowA - fill row A with normal spaces (both banks in 80 col)
clear_rowA:
        tax
        lda     rowlo,x
        sta     ptr
        lda     rowhi,x
        sta     ptr+1
        jsr     rb_poll
        lda     has80
        beq     @m
        bit     PAGE2ON
        ldy     #39
        lda     #$A0
@ca:    sta     (ptr),y
        dey
        bpl     @ca
        bit     PAGE2OFF
@m:     ldy     #39
        lda     #$A0
@cm:    sta     (ptr),y
        dey
        bpl     @cm
        rts

clear_screen:
        lda     #23
@l:     pha
        jsr     clear_rowA
        pla
        sec
        sbc     #1
        bpl     @l
        rts

; draw_at - X=col, A=row, then print the 0-terminated string at strp
draw_at:
        sta     cury
        stx     curx
draw_str:
        ldy     #0
@l:     lda     (src),y         ; src doubles as the string pointer here
        beq     @d
        ldx     curx            ; clip at the right edge (40-col pages)
        cpx     width
        bcs     @d
        jsr     conv
        sty     tmp2
        jsr     putscr
        ldy     tmp2
        iny
        bne     @l
@d:     rts

; setstr macro-ish helper: A/X = lo/hi of string -> src
.macro  STR  s, col, row
        lda     #<s
        sta     src
        lda     #>s
        sta     src+1
        ldx     #col
        lda     #row
        jsr     draw_at
.endmacro

; =====================================================================
; timing - one display frame, machine-aware, always bounded
; =====================================================================
frame_wait:
        txa                     ; callers count frames in X/Y - keep them
        pha
        tya
        pha
        jsr     fw_core
        pla
        tay
        pla
        tax
        rts
fw_core:
        lda     hasvbl
        beq     @plus           ; II/II+: calibrated ~16ms loop
        lda     VBLBIT
        and     #$80
        sta     tmp
        ldx     #0
        ldy     #120
@w1:    jsr     rb_poll         ; a frame is 16 char times - NEVER go deaf
        lda     VBLBIT          ; wait for the bit to flip...
        and     #$80
        cmp     tmp
        bne     @ph2
        inx
        bne     @w1
        dey
        bne     @w1
        rts                     ; bounded: bit never moved (weird clone)
@ph2:   sta     tmp
        ldx     #0
        ldy     #120
@w2:    jsr     rb_poll
        lda     VBLBIT          ; ...and flip back = exactly one frame,
        and     #$80            ; whichever polarity this machine uses
        cmp     tmp
        bne     @out
        inx
        bne     @w2
        dey
        bne     @w2
@out:   rts
@plus:  ldy     dly_y           ; ~16ms at 1MHz (2); 8 on the 4MHz IIc+
@d1:    ldx     #200            ; ~42 cycles/pass with the poll = ~8.4ms
@d2:    jsr     rb_poll         ; delay that stays deaf-proof
        dex
        bne     @d2
        dey
        bne     @d1
        rts

; =====================================================================
; mascot - the critter in inverse blocks, 16 wide x 5 tall
; =====================================================================
; A = top row, X = left column
draw_mascot:
        sta     tmp             ; row
        stx     mcol
        lda     #0
        sta     tmp2            ; art row index
@row:   jsr     rb_poll
        lda     tmp
        sta     cury
        lda     mcol
        sta     curx
        lda     tmp2
        asl
        asl
        asl
        asl                     ; *16
        tax
        ldy     #16
@cell:  lda     mascot_art,x
        cmp     #'X'
        beq     @blk
        lda     #$A0            ; background: normal space
        bne     @put
@blk:   lda     #$20            ; inverse space = solid block
@put:   stx     tmp3
        sty     tmp4
        jsr     putscr
        ldy     tmp4
        ldx     tmp3
        inx
        dey
        bne     @cell
        inc     tmp
        inc     tmp2
        lda     tmp2
        cmp     #5
        bne     @row
        rts

mascot_art:
        .byte   "  XXXXXXXXXXXX  "
        .byte   "  XX XXXXXX XX  "
        .byte   "XXXXXXXXXXXXXXXX"
        .byte   "  XXXXXXXXXXXX  "
        .byte   "   X X    X X   "

; =====================================================================
; boot menu
; =====================================================================
menu_screen:
        jsr     clear_screen
        lda     #0
        sta     menusel
        lda     width           ; center the mascot: (width-16)/2
        sec
        sbc     #16
        lsr
        tax
        lda     #2
        jsr     draw_mascot
        ; title, centered
        lda     width
        sec
        sbc     #37
        lsr
        tax
        lda     #<str_title
        sta     src
        lda     #>str_title
        sta     src+1
        lda     #9
        jsr     draw_at
        STR     str_by, 2, 23
        jsr     menu_draw       ; menu visible before the jingle starts
        jsr     jingle          ; once per menu visit; any key skips it
        lda     #0
        sta     blinkct
menu_loop:
        jsr     menu_draw
@key:   jsr     frame_wait      ; ~1 frame per pass (rb_poll inside);
        inc     blinkct         ; also paces the mascot's blink
        lda     blinkct
        cmp     #170            ; ~3s: eyes shut...
        bne     @b2
        jsr     eyes_close
@b2:    lda     blinkct
        cmp     #178            ; ...for ~130ms
        bne     @b3
        jsr     eyes_open
        lda     #0
        sta     blinkct
@b3:    lda     KBD
        bpl     @key
        sta     KBDSTRB
        and     #$7F
        cmp     #$0B            ; up
        beq     @up
        cmp     #$0A            ; down
        beq     @dn
        cmp     #$0D
        beq     @go
        cmp     #'1'
        bcc     @key
        cmp     #'5'
        bcs     @key
        sec
        sbc     #'1'
        sta     menusel
        jmp     @go
@up:    lda     menusel
        beq     @kj
        dec     menusel
        jmp     menu_loop
@dn:    lda     menusel
        cmp     #3
        bcs     @kj
        inc     menusel
        jmp     menu_loop
@kj:    jmp     @key
@go:    lda     menusel
        bne     @g1
        jmp     act_connect
@g1:    cmp     #1
        beq     @modem
        cmp     #2
        beq     @instr
        jmp     act_quit
@modem: jmp     page_modem
@instr: jmp     page_instr

; eyes_close/open - the menu mascot's blink. His eyes are dark cells
; punched out of the lit body: closing = filling them with inverse
; blocks. Eye cells sit at mascot row+1, columns +4 and +11.
eyes_close:
        lda     #$20            ; inverse space = lit block
        bne     eyes_put
eyes_open:
        lda     #$A0            ; normal space = dark
eyes_put:
        sta     tmp3
        lda     width
        sec
        sbc     #16
        lsr
        clc
        adc     #4              ; left eye
        sta     curx
        lda     #3              ; mascot top (2) + 1
        sta     cury
        lda     tmp3
        jsr     putscr
        lda     width
        sec
        sbc     #16
        lsr
        clc
        adc     #11             ; right eye
        sta     curx
        lda     #3
        sta     cury
        lda     tmp3
        jmp     putscr

; jingle - the menu ditty (GROOVE's melody), squeezed through the
; 1-bit speaker as cycle-counted square waves. Plays once; any key
; aborts (the keypress is left for the menu loop). spdm stretches the
; half-period loop on a 4MHz IIc+. Rests are notes with bit7 set on
; the delay byte: same timing, no speaker toggles.
jingle:
        ldx     #0
@note:  lda     jtab_d,x
        beq     @done           ; 0 = end of tune
        sta     tmp             ; delay + rest flag
        and     #$7F
        sta     tmp2            ; delay proper
        lda     jtab_w,x
        sta     tmp4            ; wave count
@wave:  jsr     jhalf
        jsr     jhalf
        dec     tmp4
        bne     @wave
        jsr     rb_poll
        lda     KBD             ; a key skips the rest of the tune
        bmi     @done
        inx
        bne     @note
@done:  rts

jhalf:  bit     tmp             ; rest? (bit7)
        bmi     @quiet
        bit     SPKR
@quiet: ldx     spdm
@rep:   ldy     tmp2
@d:     dey
        bne     @d
        dex
        bne     @rep
        rts

; GROOVE's melody at ~144bpm, up an octave (the delay byte's low 7
; bits are the half-period in 5-cycle units at 1MHz, so the beeper's
; floor is ~790Hz - and jingles live up there anyway). waves = full
; cycles per note; long notes are split so waves fits a byte.
jtab_d: .byte 126, 104|$80, 96, 85, 76, 85, 96, 96, 104|$80
        .byte 114, 104|$80, 96, 85, 64, 76, 85, 85, 96, 0
jtab_w: .byte 163, 200,    145, 82,183, 82,145,146, 134
        .byte 183, 200,    145, 82,218, 92,163,163, 145

menu_draw:
        ldx     #0
@item:  txa
        pha
        cpx     menusel
        beq     @sel
        lda     #0
        sta     invflag
        beq     @draw
@sel:   lda     #1
        sta     invflag
@draw:  txa
        asl
        tay
        lda     menu_ptrs,y
        sta     src
        lda     menu_ptrs+1,y
        sta     src+1
        lda     width
        sec
        sbc     #16
        lsr
        tax
        pla
        pha
        clc
        adc     #12             ; items at rows 12-15
        jsr     draw_at
        lda     #0
        sta     invflag
        pla
        tax
        inx
        cpx     #4
        bne     @item
        rts

act_quit:
        lda     #$02            ; command reg: DTR off, RX IRQ disabled
        sta     ACIA_CMD
        jsr     clear_screen    ; clear while 80STORE is still wired up
        lda     has80
        beq     @t
        sta     $C00C           ; back to 40-col for the BASIC prompt
        sta     STORE80OFF
        bit     PAGE2OFF
@t:     jmp     DOSWARM

; =====================================================================
; connect - junk-flush, dial, classify the modem's verdict (W-477)
; =====================================================================
act_connect:
        lda     #RULE1
        jsr     clear_rowA
        lda     #INPUTR
        jsr     clear_rowA
        STR     str_dial, 2, INPUTR
        lda     #0
        sta     dialres
        sta     mdm_c1
        lda     #$0D            ; flush any half-typed junk on the modem
        jsr     aciaput
        ldx     #15             ; ~250ms, then drop the response
@fl:    jsr     frame_wait
        dex
        bne     @fl
        lda     rb_head
        sta     rb_tail
        ldx     #0
@dial:  lda     str_atd,x
        beq     @cr
        jsr     aciaput
        inx
        bne     @dial
@cr:    lda     #$0D
        jsr     aciaput
        ldx     #45             ; ~3s dial window at 15 frames/beat... 45*4
@beat:  txa
        pha
        ldy     #4
@fw:    jsr     frame_wait
        dey
        bne     @fw
@rx:    jsr     havebyte
        beq     @ck
        jsr     getbyte
        jsr     dial_byte
        jmp     @rx
@ck:    pla
        tax
        lda     dialres
        cmp     #1
        beq     @sess           ; CONNECT
        cmp     #2
        beq     @fail           ; ERROR/BUSY/NO x
        dex
        bne     @beat
@sess:  jmp     session_start   ; silence after 3s = emulator/already online
@fail:  lda     #INPUTR
        jsr     clear_rowA
        STR     str_dfail, 2, INPUTR
        ldx     #180            ; ~3s, back to the menu
@fx:    jsr     frame_wait
        dex
        bne     @fx
        jmp     menu_screen

; dial_byte - first-letter line classifier: E/B = fail, NO.. = fail,
; CO.. = connect. Sets dialres 1/2. (Port of the GS routine.)
dial_byte:
        and     #$7F
        cmp     #$0D
        beq     @nl
        cmp     #$20
        bcc     @x
        ldx     mdm_c1
        bne     @c2
        sta     mdm_c1
        cmp     #'E'
        beq     @fail
        cmp     #'B'
        beq     @fail
        rts
@c2:    cpx     #$FF
        beq     @x
        pha
        lda     #$FF
        sta     mdm_c1
        pla
        cmp     #'O'
        bne     @x
        cpx     #'C'
        beq     @conn
        cpx     #'N'
        beq     @fail
        rts
@conn:  lda     #1
        sta     dialres
        rts
@fail:  lda     #2
        sta     dialres
@nl:    lda     #0
        sta     mdm_c1
@x:     rts

; =====================================================================
; session
; =====================================================================
session_start:
        jsr     clear_screen
        lda     #0
        tax
        jsr     draw_mascot     ; header slot: top-left
        lda     #0
        sta     curx
        sta     quitflag
        lda     #TOPROW
        sta     cury
        lda     #$0D            ; session-open probe: bridge answers with
        jsr     aciaput         ; the header (or the LOCKED notice)
main:
        jsr     draw_box
        jsr     read_line
        lda     linelen
        beq     main
        jsr     draw_box
        ; /quit handled locally and BEFORE any transmit - otherwise it
        ; hits the wire and a modem in command mode interprets it
        lda     linelen
        cmp     #5
        bne     @notq
        ldx     #4
@q:     lda     linebuf,x
        ora     #$20
        cmp     str_quit,x
        bne     @notq
        dex
        bpl     @q
        jmp     quit_to_menu
@notq:  jsr     echo_user
        jsr     send_line
        jsr     spinner
        jsr     recv_reply
        lda     quitflag
        beq     main
quit_to_menu:
        lda     #0
        sta     quitflag
        lda     rb_head         ; drop the bridge's goodbye bytes
        sta     rb_tail
        jmp     menu_screen

; draw_box preserves the transcript cursor (curx/cury belong to the
; transcript; the input row borrows them and must give them back)
draw_box:
        lda     curx
        pha
        lda     cury
        pha
        lda     #RULE1
        jsr     rule_row
        lda     #RULE2
        jsr     rule_row
        lda     #INPUTR
        jsr     clear_rowA
        lda     #INPUTR
        sta     cury
        lda     #0
        sta     curx
        lda     #'>'
        ora     #$80
        jsr     putscr
        lda     #$A0
        jsr     putscr
        pla
        sta     cury
        pla
        sta     curx
        rts

rule_row:
        sta     cury
        lda     #0
        sta     curx
        ldx     width
@l:     txa
        pha
        jsr     rb_poll
        lda     #'-'
        ora     #$80
        jsr     putscr
        pla
        tax
        dex
        bne     @l
        rts

; echo_user - "> line" into the transcript, inverse (the II's "white")
echo_user:
        lda     #1
        sta     invflag
        lda     #'>'
        jsr     cout
        lda     #' '
        jsr     cout
        ldx     #0
@l:     cpx     linelen
        beq     @d
        lda     linebuf,x
        stx     tmp3
        jsr     cout
        ldx     tmp3
        inx
        bne     @l
@d:     lda     #0
        sta     invflag
        lda     #$0D
        jsr     cout
        jmp     cout_cr_pad     ; blank line after

cout_cr_pad:
        lda     #$0D
        jmp     cout

send_line:
        ldx     #0
@l:     cpx     linelen
        beq     @d
        lda     linebuf,x
        jsr     aciaput
        inx
        bne     @l
@d:     lda     #$0D
        jmp     aciaput

; =====================================================================
; read_line - into linebuf, echo at the input row. Handles the
; bridge's idle traffic (header frames at boot, stray CRs).
; =====================================================================
read_line:
        lda     curx            ; borrow the cursor for the input row;
        sta     tcurx           ; the transcript gets it back at exit
        lda     cury
        sta     tcury
        lda     #2              ; after "> "
        sta     curx
        lda     #INPUTR
        sta     cury
        lda     #0
        sta     linelen
@key:   jsr     rb_poll
        jsr     havebyte
        beq     @kbd
        ldx     rb_tail         ; peek: only consume protocol traffic
        lda     RING,x
        and     #$7F
        cmp     #CMD_HEADER
        beq     @hdr
        cmp     #CMD_QUIT
        beq     @rq
        jsr     getbyte         ; stray byte (CONNECT echo etc): discard
        jmp     @key
@hdr:   jsr     getbyte
        jsr     do_header
        jmp     @key
@rq:    jsr     getbyte
        lda     #1
        sta     quitflag
        lda     #0
        sta     linelen
        beq     @done           ; restore the transcript cursor on this exit too
@kbd:   lda     KBD
        bpl     @key
        sta     KBDSTRB
        and     #$7F
        cmp     #$0D
        beq     @done
        cmp     #$08            ; left arrow = backspace
        beq     @bs
        cmp     #$7F
        beq     @bs
        cmp     #$20
        bcc     @key
        ldx     linelen
        cpx     #120
        bcs     @key
        sta     linebuf,x
        inc     linelen
        ldx     curx            ; echo only while it fits on the row
        cpx     width
        bcs     @key
        ora     #$80
        jsr     putscr
        jmp     @key
@bs:    lda     linelen
        beq     @key
        dec     linelen
        dec     curx
        lda     #$A0
        jsr     putscr
        dec     curx
        jmp     @key
@done:  lda     tcurx
        sta     curx
        lda     tcury
        sta     cury
        rts

; =====================================================================
; spinner - pulse until the reply's first real byte. Esc = bail to
; the menu (dead-link escape hatch).
; =====================================================================
spinner:
        lda     #0
        sta     havefirst
        sta     sp_ph
@lp:    lda     KBD
        bpl     @nk
        sta     KBDSTRB
        and     #$7F
        cmp     #$1B
        bne     @nk
        lda     #1
        sta     quitflag
        lda     #EOT            ; fake end-of-reply
        jmp     @stash
@nk:    jsr     havebyte
        beq     @draw
        jsr     getbyte
        and     #$7F
        cmp     #EOT
        beq     @stash
        cmp     #CMD_COLOR
        beq     @stash
        cmp     #CMD_BULLET
        beq     @stash
        cmp     #CMD_HEADER
        beq     @stash
        cmp     #CMD_QUIT
        beq     @q
        cmp     #$20
        bcc     @lp             ; pre-reply CR/LF: discard
        cmp     #$7F
        bcs     @lp
@stash: sta     firstbyte
        lda     #1
        sta     havefirst
        ; erase the pulse cell
        lda     cury
        pha
        lda     curx
        pha
        lda     #0
        sta     curx
        lda     #BTMROW
        sta     cury
        lda     #$A0
        jsr     putscr
        pla
        sta     curx
        pla
        sta     cury
        rts
@q:     lda     #1
        sta     quitflag
        jmp     @lp
@draw:  lda     cury
        pha
        lda     curx
        pha
        lda     #0
        sta     curx
        lda     #BTMROW
        sta     cury
        inc     sp_ph
        lda     sp_ph
        lsr
        lsr
        and     #$03
        tax
        lda     sp_glyphs,x
        ora     #$80
        jsr     putscr
        pla
        sta     curx
        pla
        sta     cury
        jsr     frame_wait
        jmp     @lp

; =====================================================================
; recv_reply - stream until EOT (mirror of the GS routine)
; =====================================================================
recv_reply:
        lda     #0
        sta     invflag
        sta     colorpend
        lda     havefirst
        beq     @next
        lda     firstbyte
        jmp     @disp
@next:  jsr     getbyte
        and     #$7F
@disp:  ldx     colorpend
        beq     @nocp
        cmp     #3              ; color 3 (white/code) -> inverse
        beq     @inv
        lda     #0
        sta     invflag
        beq     @clr
@inv:   lda     #1
        sta     invflag
@clr:   lda     #0
        sta     colorpend
        beq     @next
@nocp:  cmp     #EOT
        beq     @done
        cmp     #CMD_COLOR
        beq     @setcp
        cmp     #CMD_BULLET
        beq     @bullet
        cmp     #CMD_HEADER
        beq     @hdr
        cmp     #CMD_QUIT
        beq     @rq
        cmp     #$0A
        beq     @next
        jsr     cout
        jmp     @next
@setcp: lda     #1
        sta     colorpend
        bne     @next
@bullet:lda     #'*'
        jsr     cout
        lda     #' '
        jsr     cout
        jmp     @next
@hdr:   jsr     do_header
        jmp     @next
@rq:    lda     #1
        sta     quitflag
        bne     @next
@done:  lda     #$0D
        jsr     cout
        lda     #$0D
        jsr     cout
        lda     #0
        sta     havefirst
        rts

; =====================================================================
; do_header - 3 CR-terminated lines drawn beside the mascot (rows
; 1-3, col HDRCOL). The window scroll never touches them.
; =====================================================================
do_header:
        lda     curx
        pha
        lda     cury
        pha
        lda     #1
        sta     hdr_row
@line:  lda     #HDRCOL
        sta     curx
        lda     hdr_row
        sta     cury
@ch:    jsr     getbyte
        and     #$7F
        cmp     #$0D
        beq     @eol
        cmp     #$20
        bcc     @ch
        ldx     curx
        cpx     width
        bcs     @ch             ; truncate at the right edge
        ora     #$80
        jsr     putscr
        jmp     @ch
@eol:   ; pad the rest of the line (clears a previous longer header)
        ldx     curx
@pad:   cpx     width
        bcs     @nl
        jsr     rb_poll         ; ~60 pads = several char times
        lda     #$A0
        jsr     putscr
        ldx     curx
        jmp     @pad
@nl:    inc     hdr_row
        lda     hdr_row
        cmp     #4
        bne     @line
        pla
        sta     cury
        pla
        sta     curx
        rts

; =====================================================================
; modem console - raw keys out, raw bytes in. Esc = menu.
; =====================================================================
page_modem:
        jsr     clear_screen
        STR     str_mdm_t, 2, 1
        STR     str_mdm_h, 2, 3
        lda     #0
        sta     curx
        lda     #TOPROW
        sta     cury
@lp:    jsr     rb_poll
        jsr     havebyte
        beq     @kbd
        jsr     getbyte
        and     #$7F
        cmp     #$0A
        beq     @lp
        jsr     cout
        jmp     @lp
@kbd:   lda     KBD
        bpl     @lp
        sta     KBDSTRB
        and     #$7F
        cmp     #$1B
        beq     @out
        jsr     aciaput         ; live console: every key straight out
        jmp     @lp
@out:   jmp     menu_screen

; =====================================================================
; instructions
; =====================================================================
page_instr:
        jsr     clear_screen
        STR     str_ins_t, 2, 1
        STR     str_ins_1, 2, 3
        STR     str_ins_2, 2, 5
        STR     str_ins_3, 2, 6
        STR     str_ins_4, 2, 7
        STR     str_ins_5, 2, 9
        STR     str_ins_6, 2, 11
        STR     str_esc, 2, 22
@k:     jsr     rb_poll
        lda     KBD
        bpl     @k
        sta     KBDSTRB
        jmp     menu_screen

; =====================================================================
; strings
; =====================================================================
str_title:  .byte "Claude Code Terminal for the Apple ][",0
str_by:     .byte "by Wells Workshop",0
str_dial:   .byte "Dialing...",0
str_dfail:  .byte "Dial failed - try the modem console",0
str_atd:    .byte "ATDS=0",0
str_quit:   .byte "/quit"
str_gs:     .byte "THIS IS THE 8-BIT CLIENT - ON A IIGS RUN: BRUN COBJ",$0D,0
str_mdm_t:  .byte "Hayes AT console",0
str_mdm_h:  .byte "Keys go straight to the modem. Esc = menu.",0
str_ins_t:  .byte "Instructions",0
str_ins_1:  .byte "Talk to Claude Code from this Apple II, over a WiFi modem.",0
str_ins_2:  .byte "The bridge (on a modern computer):",0
str_ins_3:  .byte " github.com/wr/claude-code-terminal-for-apple-ii",0
str_ins_4:  .byte " python3 bridge.py --telnet --app --backend code",0
str_ins_5:  .byte "Modem: store the bridge as entry 0 (AT&Z0=host:6400, AT&W).",0
str_ins_6:  .byte "Connect on the menu dials ATDS=0 and starts the session.",0
str_esc:    .byte "Any key returns to the menu",0
sp_glyphs:  .byte "*+:+"
menu_ptrs:  .word mi0, mi1, mi2, mi3
mi0:        .byte "1. Connect",0
mi1:        .byte "2. Modem",0
mi2:        .byte "3. Instructions",0
mi3:        .byte "4. Quit to Basic",0

; text page row bases
rowlo:  .byte $00,$80,$00,$80,$00,$80,$00,$80
        .byte $28,$A8,$28,$A8,$28,$A8,$28,$A8
        .byte $50,$D0,$50,$D0,$50,$D0,$50,$D0
rowhi:  .byte $04,$04,$05,$05,$06,$06,$07,$07
        .byte $04,$04,$05,$05,$06,$06,$07,$07
        .byte $04,$04,$05,$05,$06,$06,$07,$07

; =====================================================================
; bss
; =====================================================================
rb_head:    .res 1
rb_tail:    .res 1
has80:      .res 1
hasvbl:     .res 1
width:      .res 1
quitflag:   .res 1
colorpend:  .res 1
havefirst:  .res 1
firstbyte:  .res 1
linelen:    .res 1
menusel:    .res 1
dialres:    .res 1
mdm_c1:     .res 1
sp_ph:      .res 1
hdr_row:    .res 1
mcol:       .res 1
tmp3:       .res 1
tmp4:       .res 1
tcurx:      .res 1          ; transcript cursor parked during input
tcury:      .res 1
dly_y:      .res 1          ; frame-delay outer count (2; 8 on the IIc+)
spdm:       .res 1          ; speaker half-period multiplier (1; 4 on IIc+)
blinkct:    .res 1          ; menu: frames since the last blink
linebuf:    .res 128
