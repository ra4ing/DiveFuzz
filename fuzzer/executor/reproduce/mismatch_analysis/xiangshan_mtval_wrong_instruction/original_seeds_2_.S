.globl _start
.section .text
_start:
  li x13, 0x800000000084112d
  csrw 0x301, x13
trap_vec_init:
  la x13, other_exp
  csrw 0x305, x13 # MTVEC
  la x13, other_exp_s
  csrw 0x105, x13 # STVEC
mepc_setup:
  la x13, init
  csrw 0x341, x13
init_env:
  li x26, 0x000000a900362240
  csrw 0x300, x26 # MSTATUS (mode is 0)
  li x16, -0x1
  csrw 0x3b0, x16 # pmpaddr0 = all 1s (NAPOT full coverage)
  li x16, 0x1f
  csrw 0x3a0, x16 # pmpcfg0: entry 0 = NAPOT+RWX
  li x16, 0x0
  csrw 0x3a2, x16 # pmpcfg2 = 0 (disable entries 8-15)
  sfence.vma x0, x0
  li x26, 0x0
  csrw 0x302, x26 # MEDELEG - no delegation to S-mode
  csrw 0x303, x26 # MIDELEG - no delegation to S-mode
  csrw 0x304, x26 # MIE
  csrw 0x340, x26 # MSCRATCH - init to 0 for cosim sync
  csrw 0x343, x26 # MTVAL - init to 0 for cosim sync
  csrw 0x342, x26 # MCAUSE - init to 0 for cosim sync
  csrw 0x140, x26 # SSCRATCH - init to 0 for cosim sync
  csrw 0x143, x26 # STVAL - init to 0 for cosim sync
  csrw 0x142, x26 # SCAUSE - init to 0 for cosim sync
  csrw 0x141, x26 # SEPC - init to 0 for cosim sync
  mret
init:
  fsrmi 0
  csrwi fflags, 0
  li x1, 0xc0bd7a4c7e345a89
  li x2, 0x5bff060a863b36a3
  li x3, 0x0000000000000100
  li x4, 0x0000000000000008
  li x5, 0x0000000100000000
  li x6, 0xa8323771ce428df8
  li x7, 0xffffffffffffffff
  li x8, 0x000000007fffffff
  li x9, 0x8f451cb4560907c5
  li x10, 0xb52ab792a706b47c
  li x11, 0x0000000000000007
  li x12, 0x8c052d633758fbda
  li x13, 0xffffffffffffffff
  li x14, 0xe819c7f7297e1187
  li x15, 0x00000000ffffffff
  li x5, 0x000000000000bf76
  fmv.h.x f0, x5
  li x5, 0x000000000000cce9
  fmv.h.x f1, x5
  li x5, 0x000000003f800001
  fmv.w.x f2, x5
  li x5, 0x00000000c17f49ce
  fmv.w.x f3, x5
  li x5, 0x7ff0000000000000
  fmv.d.x f4, x5
  li x5, 0x00000000c33112ed
  fmv.w.x f5, x5
  li x5, 0x40723238ffd8c561
  fmv.d.x f6, x5
  li x5, 0x7ff0000000000000
  fmv.d.x f7, x5
  li x5, 0x000000000000d27b
  fmv.h.x f8, x5
  li x5, 0x0000000000000400
  fmv.h.x f9, x5
  li x5, 0x0000000000000000
  fmv.d.x f10, x5
  li x5, 0x7fefffffffffffff
  fmv.d.x f11, x5
  la t6, mem_region
  li t5, 4096
  add t6, t6, t5
  j main
.align 12
other_exp:
.option norvc
  csrr x13, 0x341
  addi x13, x13, 4
  csrw 0x341, x13
  mret
.option rvc
other_exp_s:
.option norvc
  csrr x13, 0x141
  addi x13, x13, 4
  csrw 0x141, x13
  sret
.option rvc
.align 2
.option norvc
main:
  blt s0, t1, . + 32
  fmv.x.d s2, fs7
  rem s7, s2, t1
  subw s1, t1, t4
  csrrs a3, frm, zero
  rolw t2, s1, t2
  fcvt.l.s a1, fs9, dyn
  csrrs s3, frm, zero
  fwd_0:
  beq s11, zero, . + 28
  flw fs4, -1212(t6)
  clmulh s10, s0, s11
  remu sp, tp, s3
  lw s5, -1484(t6)
  rem s1, s3, a2
  fcvt.s.lu fa2, s0, dyn
  fwd_1:
  jal t2, . + 28
  clmulh s8, s4, s8
  remw s10, s0, s0
  mulw gp, gp, s8
  fcvt.lu.d a6, fa7, dyn
  bext s11, s2, s9
  ori a1, a6, -1136
  fwd_2:
  blt s5, s0, . + 20
  fmsub.d ft11, ft10, ft1, ft0, dyn
  rol s3, s3, tp
  andi t2, t0, 49
  subw s11, s3, s3
  fwd_3:
  lui s10, 1046545
  addiw s10, s10, -119
  slli s10, s10, 12
  addi s10, s10, -1184
  bne s2, tp, . + 20
  fence.i
  subw s7, tp, a7
  roriw t0, s9, 11
  fcvt.s.l fs2, t0, dyn
  fwd_4:
  addi a3, zero, 1
  addi a1, zero, -1
  bge tp, s3, . + 16
  csrrw a1, frm, t1
  fmsub.d ft1, fa7, ft1, ft7, dyn
  fence.i
  fwd_5:
  bne t1, t1, . + 24
  bset a2, a4, t2
  remuw a6, s2, t2
  fld fs4, -816(t6)
  packh s10, a6, t2
  fcvt.l.d t4, ft3, dyn
  fwd_6:
  bne s1, s7, . + 36
  fdiv.d fa4, ft1, ft10, dyn
  fcvt.d.l fs1, s7, dyn
  fmadd.d ft3, ft10, fs5, fa4, dyn
  binv a5, a1, a2
  flw fs0, 192(t6)
  fcvt.s.l fs8, a2, dyn
  fence.i
  fcvt.lu.d s6, fs8, dyn
  fwd_7:
  jal s7, . + 20
  subw ra, a2, t0
  fcvt.s.d fs2, ft9, dyn
  fcvt.lu.s s4, fa2, dyn
  rori t3, s7, 0
  fwd_8:
  bgeu a7, s3, . + 12
  bset sp, t3, t3
  slli s4, t3, 63
  fwd_9:
  lui s9, 22793
  addiw s9, s9, -163
  slli s9, s9, 12
  addi s9, s9, -551
  blt s2, a4, . + 20
  fcvt.l.d a0, ft10, dyn
  fcvt.s.l fs4, s3, dyn
  clmulh a1, s5, s3
  fcvt.s.l fs5, a0, dyn
  fwd_10:
  addi s11, zero, 2
  bwd_0:
  csrrci s10, vsie, 1
  flw fa4, -1616(t6)
  fcvt.d.l fs6, gp, dyn
  addi s11, s11, -1
  bne s11, zero, bwd_0
  jal a5, . + 12
  lbu s9, 1339(t6)
  fence.i
  fwd_11:
  lui s1, 32768
  slli s1, s1, 12
  addi s1, s1, -1
  auipc s2, 0
  addi s2, s2, 28
  jalr a4, 0(s2)
  fcvt.l.s tp, fa1, dyn
  remuw s5, zero, tp
  rorw t3, s5, tp
  csrrw s4, fflags, tp
  fwd_12:
  auipc a3, 0
  addi a3, a3, 20
  jalr gp, 0(a3)
  csrrs a4, frm, zero
  orn t2, a4, t2
  fwd_13:
  bltu s1, s0, . + 20
  divuw s10, a1, s8
  csrrs t0, vsie, t0
  flw fs4, -1368(t6)
  fnmadd.d fa2, fs4, fa2, ft7, dyn
  fwd_14:
  beq sp, s9, . + 24
  sltu t3, s7, s9
  flt.d s6, fa5, fa3
  slliw a0, s4, 7
  clmul a5, s11, a0
  flw ft8, 700(t6)
  fwd_15:
  auipc s4, 0
  addi s4, s4, 32
  jalr s8, 0(s4)
  clmulh a4, a1, a3
  binv a6, a3, a4
  fmv.d.x fa7, a3
  flw fs3, -992(t6)
  bclr s5, s1, a1
  fwd_16:
  bge t0, t0, . + 16
  lw t3, 220(t6)
  divuw a7, t3, tp
  addi s0, a3, 1
  fwd_17:
  bge s0, s1, . + 8
  roriw a6, t2, 21
  fwd_18:
  bgeu a3, t3, . + 28
  binv t4, t0, t2
  fcvt.s.l fa1, s8, dyn
  roriw s9, t3, 0
  flw fs7, 152(t6)
  clmulh a2, t4, t3
  fcvt.lu.s tp, fa7, dyn
  fwd_19:
  bgeu t1, s10, . + 12
  divu t0, s9, s9
  orn a1, s10, a1
  fwd_20:
  bne a1, a1, . + 16
  mulw gp, s9, s9
  pack a6, s7, gp
  rorw a4, s4, gp
  fwd_21:
  lui s11, 1022330
  addiw s11, s11, -1644
  slli s11, s11, 12
  addi s11, s11, 1498
  bge ra, ra, . + 28
  bclr zero, t1, sp
  fcvt.d.lu ft11, t1, dyn
  feq.d a2, ft5, ft10
  fadd.d fs7, ft10, fs7, dyn
  flw ft5, -1020(t6)
  fclass.d s2, ft11
  fwd_22:
  jal a2, . + 32
  fmv.x.d gp, ft5
  fmsub.d fs10, fs7, ft9, ft11, dyn
  mulhsu s5, a7, s5
  remw a1, a1, s4
  flw fs8, 1336(t6)
  sll a0, sp, a0
  fmadd.d fa1, ft11, fa1, fa1, dyn
  fwd_23:
  bgeu s3, a6, . + 12
  fmadd.d ft5, fa1, fs10, fs2, dyn
  rem a5, t0, a6
  fwd_24:
  auipc s9, 0
  addi s9, s9, 36
  jalr a0, 0(s9)
  binv gp, a3, a3
  clmulh a4, s4, gp
  packw zero, a5, s4
  fcvt.lu.s s7, fs11, dyn
  binv tp, a4, a5
  mulhsu s8, tp, a4
  fwd_25:
  jal s3, . + 16
  remw sp, a2, a1
  fcvt.d.lu fa5, s9, dyn
  slti s7, tp, 0
  fwd_26:
  lui s1, 1015808
  slli s1, s1, 12
  lui t2, 1027873
  addiw t2, t2, -920
  slli t2, t2, 12
  addi t2, t2, -1296
  beq t4, a7, . + 28
  fcvt.s.lu fa0, ra, dyn
  binv a4, t3, gp
  addi a0, s6, -1
  rori s4, s7, 63
  clmul t2, t4, ra
  ror a2, a0, a4
  fwd_27:
  addi t3, zero, -1
  bltu sp, ra, . + 16
  clmul t0, a5, t0
  lwu s1, -1844(t6)
  flw fa0, -676(t6)
  fwd_28:
  bne sp, a5, . + 24
  bset ra, s11, sp
  binv s3, s1, a5
  rolw tp, a5, gp
  fcvt.d.lu fa5, s2, dyn
  fcvt.d.s fs11, fs5
  fwd_29:
  auipc a0, 0
  addi a0, a0, 36
  jalr tp, 0(a0)
  orn s2, a0, s11
  flw ft11, 1812(t6)
  packh s6, s6, a5
  divw a7, t1, s6
  rori s4, s4, 52
  divw a3, s2, tp
  fwd_30:
  auipc t1, 0
  addi t1, t1, 40
  jalr s11, 0(t1)
  fcvt.s.lu fa5, s11, dyn
  clmul s7, t1, s7
  csrrci sp, mcycle, 30
  csrrsi a3, hpmcounter5, 22
  clmulh s4, s11, tp
  fence.i
  srli s6, sp, 1
  fwd_31:
  bltu t4, a5, . + 28
  clmulh s5, s7, t2
  clmul s0, s5, s0
  csrrsi gp, hpmcounter30, 3
  mulhsu zero, s2, s2
  bclr s7, t2, s2
  srlw s9, s6, s7
  fwd_32:
  auipc s8, 0
  addi s8, s8, 32
  jalr s2, 0(s8)
  fmin.d fs10, ft0, ft3
  csrrs t1, fflags, zero
  packw s4, a5, s4
  clmul t0, t0, a5
  pack sp, s5, t1
  fwd_33:
  bgeu zero, s4, . + 32
  bext t0, s10, zero
  csrrc a2, mimpid, s4
  bext s8, t3, s4
  fcvt.s.lu fs10, s4, dyn
  flw ft1, -1608(t6)
  binv ra, t3, a2
  csrrci sp, medeleg, 1
  fwd_34:
  bgeu a3, s11, . + 32
  fence.i
  clmulh a6, s6, s6
  lwu s7, 252(t6)
  sraw t3, a1, t3
  fence.i
  bclr t0, t3, s6
  ror tp, t3, a3
  fwd_35:
  blt s6, s2, . + 24
  flw ft7, 612(t6)
  sub s9, s3, s6
  div a5, s6, a1
  fcvt.d.s fs9, fs1
  fcvt.s.l fs8, t4, dyn
  fwd_36:
  addi a5, zero, -1
  auipc s5, 0
  addi s5, s5, 32
  jalr a7, 0(s5)
  flw fs0, -184(t6)
  mulhu t2, ra, a7
  rori s7, s10, 2
  csrrc sp, mhpmcounter29, s2
  remuw s10, s10, s10
  fwd_37:
  lui a7, 29221
  addiw a7, a7, 1960
  slli a7, a7, 12
  addi a7, a7, -1438
  bge a4, s8, . + 28
  fcvt.lu.s s11, ft11, dyn
  fcvt.d.l fs7, s6, dyn
  remuw a3, s11, s6
  remw zero, zero, a3
  csrrs sp, frm, zero
  clmul ra, s5, t1
  fwd_38:
  bne zero, s4, . + 32
  fcvt.d.lu fa5, zero, dyn
  fcvt.l.d a5, fa5, dyn
  fmadd.d ft10, fs4, ft8, fa5, dyn
  rol a1, s9, t0
  clmul s11, s2, a6
  slli s0, s11, 49
  fence.i
  fwd_39:
  bne sp, s2, . + 28
  rorw s7, t0, t1
  divu a3, t4, s7
  csrrsi a4, mscratch, 2
  fcvt.lu.s tp, fs3, dyn
  fcvt.lu.d s11, fs3, dyn
  clmul a7, a7, s11
  fwd_40:
  auipc s10, 0
  addi s10, s10, 36
  jalr s6, 0(s10)
  mulhu a7, s11, s11
  rolw gp, tp, s6
  divw s2, s8, s2
  mul zero, s6, s6
  xnor s3, s6, gp
  fsgnj.d ft8, ft11, ft6
  fwd_41:
  bge a4, ra, . + 20
  mulw a0, gp, s0
  sub t2, a0, gp
  rorw s4, s4, a0
  fmv.x.d a3, fa7
  fwd_42:
  auipc a7, 0
  addi a7, a7, 36
  jalr a5, 0(a7)
  remuw gp, zero, a0
  csrrw a1, frm, a1
  ld s0, -104(t6)
  rori t3, t3, 1
  fcvt.d.lu fs1, a0, dyn
  divu s1, t1, gp
  fwd_43:
  auipc a5, 0
  addi a5, a5, 20
  jalr t3, 0(a5)
  addiw a0, sp, -1
  bext s0, sp, s2
  fwd_44:
  bltu t4, t4, . + 20
  addw t2, a7, s7
  flw ft1, -672(t6)
  flw fs0, -1208(t6)
  packh s0, t4, s0
  fwd_45:
  addi s11, zero, 4
  bwd_1:
  mulw a2, s9, ra
  csrrci s8, hpmcounter10, 17
  clmul s9, a2, a0
  lw t4, 856(t6)
  addi s11, s11, -1
  bne s11, zero, bwd_1
  beq s7, s8, . + 20
  packw s2, a4, t1
  or a2, a1, t2
  srlw s11, a4, t3
  clmul gp, t1, a6
  fwd_46:
  addi s6, zero, -1
  jal s10, . + 16
  packw s8, zero, a5
  fcvt.l.s sp, fs11, dyn
  remuw t0, s8, s10
  fwd_47:
  lui s7, 32768
  slli s7, s7, 12
  addi s7, s7, -1
  bge s4, s4, . + 16
  fcvt.l.d a2, ft4, dyn
  flt.d s10, fa0, ft4
  sll t3, s9, s10
  fwd_48:
  bltu a0, a0, . + 20
  fmv.x.d s11, fa6
  xor gp, s8, a3
  flw fa3, 1832(t6)
  csrrs ra, sstatus, a4
  fwd_49:
  beq a0, a1, . + 16
  flw ft5, 404(t6)
  xnor s11, a1, t3
  fmv.x.d a6, ft2
  fwd_50:
  addi s11, zero, 4
  bwd_2:
  orn s5, sp, sp
  csrrw s3, fflags, sp
  fence.i
  bset a6, sp, s9
  fsgnj.d ft2, fs2, fa1
  addi s11, s11, -1
  bne s11, zero, bwd_2
  auipc t1, 0
  addi t1, t1, 32
  jalr t0, 0(t1)
  clmulh t2, t2, gp
  packw s5, a3, a6
  csrrc a5, mhpmcounter19, t0
  fcvt.s.lu ft0, a5, dyn
  flw ft8, -1516(t6)
  fwd_51:
  bne s6, gp, . + 20
  fmv.d.x fa1, zero
  rol s4, a5, s4
  fcvt.s.l fs7, a5, dyn
  clmulh a0, s4, a5
  fwd_52:
  beq a6, s0, . + 32
  fmul.d ft5, fa7, fa7, dyn
  roriw gp, s11, 31
  pack a5, gp, s11
  srai a1, t1, 53
  fcvt.lu.s s1, fa0, dyn
  flw fs10, -624(t6)
  div s10, s10, gp
  fwd_53:
  bgeu a3, s5, . + 28
  fcvt.d.l fs4, t2, dyn
  fence.i
  rol zero, zero, a3
  srli t1, a2, 0
  fcvt.s.lu fa2, a1, dyn
  csrrs tp, frm, zero
  fwd_54:
  beq s3, s6, . + 16
  divu s5, s4, a1
  bclr a7, s5, t2
  flw ft7, 1024(t6)
  fwd_55:
  bge zero, s6, . + 32
  divu a7, a7, a7
  binv s7, tp, tp
  fsub.d fa5, fa4, ft1, dyn
  remuw a5, a7, s7
  divuw s10, a7, a5
  clmul s9, s10, s0
  fcvt.d.lu fs2, s7, dyn
  fwd_56:
  lui tp, 1028621
  addiw tp, tp, 1372
  slli tp, tp, 12
  addi tp, tp, -253
  blt s3, s6, . + 24
  fcvt.lu.s s11, fs3, dyn
  fcvt.lu.s a1, ft1, dyn
  rori s8, s0, 0
  mulhsu gp, s11, s8
  feq.d s10, ft3, fs2
  fwd_57:
  bge t3, s9, . + 16
  csrrw a2, frm, s11
  packh s1, s1, t4
  orn t2, s9, s1
  fwd_58:
  lui s2, 1023398
  addiw s2, s2, -260
  slli s2, s2, 12
  addi s2, s2, 749
  auipc s9, 0
  addi s9, s9, 36
  jalr s0, 0(s9)
  subw a1, s10, a1
  rori a3, s0, 63
  fcvt.d.l fa5, s0, dyn
  divw a4, a3, a4
  divuw s2, s0, a3
  divu s7, a3, s0
  fwd_59:
  addi s11, zero, 4
  bwd_3:
  fcvt.lu.d t1, ft0, dyn
  fence.i
  addi s11, s11, -1
  bne s11, zero, bwd_3
  beq s1, s9, . + 20
  flw ft3, 912(t6)
  fence.i
  mulhu a4, t1, t1
  fence.i
  fwd_60:
  beq a5, t1, . + 24
  flw fa5, -440(t6)
  csrrs s4, frm, zero
  csrrw s4, frm, a7
  fcvt.l.d s6, fs2, dyn
  rorw a4, s11, t1
  fwd_61:
  beq a1, sp, . + 16
  packh s6, a7, sp
  csrrw s11, fflags, a2
  csrrw a1, hideleg, a1
  fwd_62:
  bge s6, a1, . + 16
  sllw zero, s0, s5
  fmadd.d ft0, fs2, fa4, fs0, dyn
  auipc a3, 1
  fwd_63:
  beq s4, a3, . + 20
  fcvt.s.lu fs0, a4, dyn
  sllw s10, a7, a3
  orn s7, s7, s10
  csrrs zero, frm, zero
  fwd_64:
  bgeu t2, sp, . + 28
  fmv.d.x ft9, s4
  fmv.d.x fs0, s8
  fmv.d.x fs10, zero
  mulw a1, a1, a3
  lw s0, 1296(t6)
  fcvt.d.lu fs6, gp, dyn
  fwd_65:
  bne a2, s8, . + 32
  packh sp, s8, s5
  fence.i
  bext s7, s5, a1
  rori s3, s7, 1
  bext s2, s3, t3
  div t3, s3, t3
  csrrci t0, mtval2, 0
  fwd_66:
  jal zero, . + 12
  clmulh s4, s11, t4
  flw ft6, 1124(t6)
  fwd_67:
  addi s11, zero, 4
  bwd_4:
  rolw a3, s3, s4
  flw fa4, -848(t6)
  flw fs11, -1444(t6)
  rorw s1, s7, s4
  addiw a2, s8, 0
  fcvt.l.d a4, ft1, dyn
  bext t4, zero, a2
  addi s11, s11, -1
  bne s11, zero, bwd_4
  auipc s0, 0
  addi s0, s0, 28
  jalr s7, 0(s0)
  fcvt.d.lu fs5, a4, dyn
  fsqrt.d ft11, fs5, dyn
  sraw a0, t4, t4
  slt t3, s11, a0
  fwd_68:
  bltu a7, s7, . + 28
  slli t4, s0, 51
  clmulh a5, t4, a6
  csrrsi s1, marchid, 3
  csrrwi s9, pmpcfg0, 1
  bclr s6, a5, a1
  subw s7, s1, s5
  fwd_69:
  lui a5, 22936
  addiw a5, a5, -1130
  slli a5, a5, 12
  addi a5, a5, 1549
  bltu t4, s11, . + 20
  subw s7, s7, s10
  fcvt.lu.d s6, ft10, dyn
  remuw t1, gp, s6
  fmax.d fs3, fs8, fs0
  fwd_70:
  blt s3, s3, . + 16
  clmul t0, a1, s3
  flt.d t2, ft4, fs10
  pack s11, s11, a1
  fwd_71:
  beq s11, s11, . + 20
  remw zero, sp, t2
  fcvt.l.d t3, fs5, dyn
  fcvt.d.l ft4, s7, dyn
  flw ft9, -696(t6)
  fwd_72:
  bgeu s8, s10, . + 32
  fence.i
  fence.i
  clmulh t3, s11, t3
  fcvt.d.w fa6, s11
  fcvt.lu.s t4, ft9, dyn
  xnor a6, a6, t4
  fence.i
  fwd_73:
  auipc a3, 0
  addi a3, a3, 32
  jalr gp, 0(a3)
  csrrw a0, fflags, t2
  fcvt.s.l fs5, s11, dyn
  div s6, a0, s9
  srlw s1, s1, s2
  csrrsi s0, vsscratch, 0
  fwd_74:
  lui s4, 19194
  addiw s4, s4, -2044
  slli s4, s4, 12
  addi s4, s4, 1332
  bgeu ra, t2, . + 24
  rolw s11, a1, s11
  lwu t4, -668(t6)
  ror t1, s3, ra
  fcvt.d.lu ft5, ra, dyn
  bset a6, t4, t2
  fwd_75:
  bgeu t2, t2, . + 16
  rorw s5, s9, t2
  divu s3, s2, s9
  rolw zero, a2, s0
  fwd_76:
  beq t3, s0, . + 24
  bext s8, s9, zero
  ld t3, 1776(t6)
  lbu a0, -565(t6)
  rorw s2, t3, s2
  csrrc zero, senvcfg, a6
  fwd_77:
  bgeu zero, s11, . + 16
  rol a5, s8, a7
  roriw t0, s4, 5
  clmulh a1, a1, gp
  fwd_78:
  addi s11, zero, 7
  bwd_5:
  fcvt.lu.d a2, ft3, dyn
  roriw a7, a5, 11
  lb t4, 1931(t6)
  fence.i
  binv t2, a5, a5
  rolw s9, t4, a1
  mulhsu s5, t4, s5
  addi s11, s11, -1
  bne s11, zero, bwd_5
  lui t2, 1015808
  slli t2, t2, 12
  beq s3, t4, . + 28
  bext ra, t4, s3
  lb a4, 1709(t6)
  mulhsu s7, s6, s7
  flw fs4, 1576(t6)
  fence.i
  ori s1, s7, 1
  fwd_79:
  bge s11, s0, . + 28
  clmul s7, s4, s11
  fcvt.l.s s8, ft3, dyn
  csrrwi sp, hpmcounter20, 31
  fcvt.l.d s2, ft5, dyn
  andn a6, a6, sp
  clmulh s9, a6, sp
  fwd_80:
  blt ra, a2, . + 16
  fsgnj.d ft0, ft2, fa7
  csrrs t3, hgatp, s8
  bext s7, t2, t3
  fwd_81:
  beq t2, tp, . + 32
  pack zero, s4, gp
  bext s3, t2, t2
  clmulh tp, zero, s3
  csrrc s10, hpmcounter20, s10
  bset t1, s1, s3
  fence.i
  divw s9, s9, s10
  fwd_82:
  beq ra, gp, . + 16
  clmulh a0, gp, sp
  csrrs t2, frm, zero
  flw ft0, -292(t6)
  fwd_83:
  blt s6, a5, . + 12
  csrrs a0, sscratch, s10
  fcvt.lu.s zero, fs10, dyn
  fwd_84:
  auipc ra, 0
  addi ra, ra, 32
  jalr a7, 0(ra)
  flw ft7, 956(t6)
  fmv.x.d t2, fs3
  lwu t0, 116(t6)
  rol tp, s11, t2
  remw s8, t0, a7
  fwd_85:
  blt t0, s11, . + 32
  roriw ra, s11, 21
  remw a3, ra, s9
  mulw a4, t4, gp
  rol tp, a3, s4
  fmv.x.d s5, ft6
  flw fs6, 1144(t6)
  rori s11, t3, 37
  fwd_86:
  blt s2, s10, . + 24
  lw s8, 1068(t6)
  flw fa7, 16(t6)
  flw fs11, 304(t6)
  mulw s7, ra, s8
  fence.i
  fwd_87:
  lui s11, 1017409
  addiw s11, s11, 2034
  slli s11, s11, 12
  addi s11, s11, 2045
  auipc s5, 0
  addi s5, s5, 24
  jalr a5, 0(s5)
  csrrc s1, hpmcounter17, gp
  flw fa1, -1152(t6)
  csrrsi t0, sip, 28
  fwd_88:
  bge a7, s6, . + 20
  fcvt.lu.s a6, fs0, dyn
  fence.i
  flw ft8, 1380(t6)
  flw fs9, -2008(t6)
  fwd_89:
  auipc s4, 0
  addi s4, s4, 20
  jalr s8, 0(s4)
  divu s9, s9, s10
  bext s2, zero, s9
  fwd_90:
  bltu s4, ra, . + 20
  fcvt.d.lu fs8, s10, dyn
  fmv.d.x fs11, t4
  ror a2, t2, s2
  fence.i
  fwd_91:
  addi s11, zero, 5
  bwd_6:
  div s6, t1, tp
  addi s11, s11, -1
  bne s11, zero, bwd_6
  bgeu t0, s1, . + 12
  clmulh ra, ra, t3
  rori s5, t0, 60
  fwd_92:
  beq gp, gp, . + 20
  packh a0, s2, a6
  clmulh a2, a6, a0
  bset tp, s1, a2
  bclr t3, a2, a0
  fwd_93:
  addi s11, zero, 6
  bwd_7:
  fmv.d.x fs1, t1
  bset t3, a1, t4
  flw ft0, 1008(t6)
  mulw s5, t1, a4
  fmv.d.x fs9, t3
  sub a2, s4, a3
  bset t2, t1, s5
  addi s11, s11, -1
  bne s11, zero, bwd_7
  bge t2, s4, . + 24
  fcvt.s.l fs9, s10, dyn
  divuw a1, a5, t2
  srli s0, s0, 23
  binv s10, s0, s5
  clmul s6, tp, s10
  fwd_94:
  bge a7, t0, . + 12
  clmul a3, s4, tp
  clmulh s7, a7, gp
  fwd_95:
  bgeu a0, s1, . + 16
  fcvt.d.l fs4, s1, dyn
  fcvt.d.lu fa7, s1, dyn
  fcvt.s.lu ft0, t0, dyn
  fwd_96:
  bltu s10, s5, . + 28
  fnmsub.d ft6, fs3, fa7, fa6, dyn
  clmulh gp, s7, s2
  sllw s5, s9, s2
  fcvt.lu.s s3, ft6, dyn
  binv s0, s11, s11
  lw a5, -660(t6)
  fwd_97:
  bltu s9, s8, . + 20
  rem a5, a5, s3
  rolw s0, a5, s2
  remw t1, a0, s2
  ori a5, t1, 2047
  fwd_98:
  bgeu s4, a6, . + 20
  fcvt.w.d t0, ft9, dyn
  srai gp, t0, 0
  fcvt.d.l ft5, zero, dyn
  fence.i
  fwd_99:
  beq t2, a5, . + 24
  xnor a1, t0, a5
  flw fs7, 1356(t6)
  fmv.d.x ft3, t3
  fcvt.lu.d s1, ft10, dyn
  remu a3, a1, s1
  fwd_100:
  lui s7, 1036236
  addiw s7, s7, 1146
  slli s7, s7, 12
  addi s7, s7, -386
  bgeu s3, s3, . + 20
  packw s4, s5, s9
  fence.i
  clmul gp, gp, s4
  ori a3, s3, -1877
  fwd_101:
  beq s2, s2, . + 20
  csrrw a0, frm, a1
  pack a2, a1, a1
  bclr a5, t4, a2
  fcvt.d.l fs11, a5, dyn
  fwd_102:
  bltu s11, s6, . + 8
  rolw a4, a4, t2
  fwd_103:
  jal s5, . + 28
  bext gp, t3, s5
  mulhsu a6, s9, t0
  csrrw s2, fflags, s5
  xnor s3, gp, s2
  clmul a7, s5, a7
  fence.i
  fwd_104:
  jal a0, . + 16
  sraw tp, a6, s1
  packw s0, s0, s9
  lhu ra, -1444(t6)
  fwd_105:
  jal a3, . + 12
  flw ft11, 1404(t6)
  rori s6, s6, 1
  fwd_106:
  beq a7, sp, . + 32
  remu a4, t4, t4
  fcvt.l.d t0, fs11, dyn
  fence.i
  clmulh a6, a2, a5
  flw ft5, 1812(t6)
  clmul t2, t2, tp
  fence.i
  fwd_107:
  bge t3, gp, . + 32
  fcvt.lu.d s9, fs3, dyn
  remuw s0, gp, s0
  bext sp, gp, s0
  flw ft9, 196(t6)
  andi a7, sp, 2047
  fence.i
  xnor a2, a7, a2
  fwd_108:
  auipc s9, 0
  addi s9, s9, 28
  jalr zero, 0(s9)
  feq.d t2, ft0, fs1
  fcvt.d.l fa4, sp, dyn
  flw ft2, -1492(t6)
  fence.i
  fwd_109:
  lui a2, 32768
  slli a2, a2, 12
  addi a2, a2, -1
  bgeu s6, t2, . + 16
  mulw zero, s6, s1
  fcvt.l.s s1, fs11, dyn
  ror sp, zero, s4
  fwd_110:
  bgeu t2, s2, . + 16
  clmul sp, t2, s2
  fsgnj.d fa2, ft8, fs10
  fcvt.l.d s7, fs3, dyn
  fwd_111:
  lui s10, 1034217
  addiw s10, s10, 1552
  slli s10, s10, 12
  addi s10, s10, 223
  beq s0, a6, . + 24
  clmulh s1, s9, s5
  fence.i
  mul s11, s5, s5
  divw a0, t3, s1
  fcvt.l.s zero, fs4, dyn
  fwd_112:
  bge a4, t1, . + 24
  flw fs1, 1020(t6)
  fcvt.s.lu ft4, s3, dyn
  divw s9, a7, a0
  fcvt.l.s s1, ft0, dyn
  rorw a7, a4, s1
  fwd_113:
  addi s11, zero, 3
  bwd_8:
  csrrs s8, mhpmcounter24, s10
  xnor t3, s0, s8
  flw fs8, -608(t6)
  fence.i
  fmv.d.x fs3, tp
  addi s11, s11, -1
  bne s11, zero, bwd_8
  lui t4, 1020712
  addiw t4, t4, -728
  slli t4, t4, 12
  addi t4, t4, -612
  addi s11, zero, 8
  bwd_9:
  divu s6, a1, a5
  fsqrt.d ft1, fs4, dyn
  clmulh t1, a4, a5
  lw t3, 188(t6)
  fcvt.lu.s s10, ft4, dyn
  addi gp, t3, -279
  rolw a7, t3, gp
  fcvt.w.d a3, ft5, dyn
  addi s11, s11, -1
  bne s11, zero, bwd_9
  blt a5, a0, . + 12
  divuw s9, a6, s9
  clmul s5, ra, ra
  fwd_114:
  bltu a0, tp, . + 20
  divuw s2, a0, t0
  addw s7, s2, a4
  roriw t0, s2, 0
  ebreak
  fwd_115:
  bgeu a3, t1, . + 32
  fmv.x.d a2, fa4
  ror s3, zero, a3
  fld fs0, 104(t6)
  fcvt.lu.d a7, ft1, dyn
  srlw a2, a7, a2
  auipc a3, 1048575
  packh a6, a7, a6
  fwd_116:
  beq t1, a5, . + 20
  fcvt.s.d ft6, fs9, dyn
  andn a1, a4, s6
  fcvt.l.s a0, ft3, dyn
  csrrs sp, frm, zero
  fwd_117:
  blt t0, s0, . + 20
  sllw t0, t4, a7
  rol a4, t0, t0
  fcvt.lu.d s4, fa7, dyn
  rori s8, t0, 0
  fwd_118:
  addi s11, zero, 4
  bwd_10:
  flw fa0, 1532(t6)
  fcvt.l.d t3, fa0, dyn
  fence.i
  mul a7, a7, a7
  addi s11, s11, -1
  bne s11, zero, bwd_10
  auipc s1, 0
  addi s1, s1, 40
  jalr ra, 0(s1)
  csrrw gp, hpmcounter20, a2
  ror sp, s6, ra
  fcvt.w.d a3, fa7, dyn
  roriw s11, a3, 1
  fcvt.lu.d a5, fs5, dyn
  mulhu t4, t4, a3
  mulw s5, t4, t0
  fwd_119:
  lui t3, 1017150
  addiw t3, t3, 30
  slli t3, t3, 12
  addi t3, t3, -760
  jal a0, . + 12
  mulhu s7, a4, t0
  csrrw zero, frm, a4
  fwd_120:
  blt a7, a7, . + 32
  fence.i
  mulw s2, tp, a3
  fence.i
  fence.i
  csrrs s1, frm, zero
  clmul s7, s1, a3
  fence.i
  fwd_121:
  bltu a1, ra, . + 16
  clmulh s3, s1, s1
  fcvt.l.s zero, ft5, dyn
  fence.i
  fwd_122:
  blt t3, s6, . + 24
  orn t2, s7, s11
  or a7, gp, t3
  srli t4, a7, 17
  remuw a4, t4, a4
  fle.d t1, ft6, fs10
  fwd_123:
  addi s11, zero, 1
  bwd_11:
  bclr t2, t3, s11
  binv a3, s1, t2
  fcvt.l.s t4, fs1, dyn
  sraiw s1, a3, 0
  flw fs9, -984(t6)
  bset s10, t2, t2
  addi s11, s11, -1
  bne s11, zero, bwd_11
  bgeu a0, a3, . + 20
  fence.i
  fmin.d ft7, fs3, fs3
  flw fa4, 1532(t6)
  rorw t0, t4, s1
  fwd_124:
  addi s3, zero, 1
  lui a0, 1046397
  addiw a0, a0, -1226
  slli a0, a0, 12
  addi a0, a0, 350
  beq s0, t1, . + 24
  remuw t0, zero, t1
  or a6, s0, t0
  orn t2, t2, a3
  fcvt.l.d s8, fa7, dyn
  sllw s7, t0, a6
  fwd_125:
  bge s7, a6, . + 16
  clmulh s9, s11, gp
  clmul s3, s8, s3
  fcvt.s.l ft5, s3, dyn
  fwd_126:
  jal s10, . + 20
  csrrci a2, vxsat, 26
  lbu t0, -2009(t6)
  remu a7, a7, s3
  csrrs gp, mhpmcounter30, t0
  fwd_127:
  bltu s3, s7, . + 16
  clmulh a7, s1, s1
  clmul s5, s7, a7
  clmulh t4, t2, s5
  fwd_128:
  bne t1, a6, . + 20
  fence.i
  clmul s6, s10, t1
  xori s2, a2, 0
  binv s4, t0, a5
  fwd_129:
  bgeu s6, sp, . + 16
  bclr gp, sp, sp
  fcvt.s.l fs0, gp, dyn
  andn s1, t0, s6
  fwd_130:
  bltu t0, s7, . + 20
  mulw t3, t3, s6
  clmul s9, t2, ra
  bset t4, s9, a5
  rolw a6, a6, a6
  fwd_131:
  bltu a5, s2, . + 16
  flw fs9, 8(t6)
  srli ra, s2, 21
  clmulh s9, s8, s3
  fwd_132:
  addi s0, zero, -1
  jal s7, . + 28
  packw a4, s7, s7
  slli a2, s0, 28
  sraiw s10, s10, 31
  csrrw s3, frm, a4
  fence.i
  binv s4, s10, s3
  fwd_133:
  bltu s1, s11, . + 12
  fnmadd.d fs6, ft3, ft3, fs9, dyn
  roriw s2, s1, 24
  fwd_134:
  auipc a4, 0
  addi a4, a4, 20
  jalr t0, 0(a4)
  xnor sp, s2, s2
  csrrw s1, frm, s1
  fwd_135:
  beq s8, ra, . + 32
  fcvt.w.d sp, ft3, dyn
  fmv.d.x fs8, ra
  add s7, s3, s8
  csrrs a7, frm, zero
  fcvt.s.lu fs1, s7, dyn
  flw fs2, 1276(t6)
  divuw s0, t4, s6
  fwd_136:
  bltu a5, s1, . + 4
  fwd_137:
  bgeu sp, a4, . + 20
  mulw a5, a5, sp
  fcvt.s.l ft5, a5, dyn
  binv s5, zero, s9
  fmax.d fs7, ft8, fs6
  fwd_138:
  jal s0, . + 20
  clmul a7, s7, a1
  orn tp, a1, s8
  flw ft1, 1464(t6)
  fmv.x.d sp, ft0
  fwd_139:
  blt t1, s7, . + 28
  fcvt.d.l fa7, t3, dyn
  bclr zero, a4, s7
  divu a4, zero, zero
  rorw a1, s11, a5
  csrrw s1, menvcfg, s6
  mulhsu s5, a4, a1
  fwd_140:
  bge a6, t2, . + 32
  or a1, sp, sp
  flw fs7, 816(t6)
  fnmadd.d fs0, fs5, fs7, fs7, dyn
  fcvt.s.l ft9, t3, dyn
  subw a7, t2, a6
  fence.i
  rol a4, a7, sp
  fwd_141:
  lui sp, 32768
  slli sp, sp, 12
  addi sp, sp, -1
  bgeu zero, a1, . + 12
  fnmadd.d fs8, ft9, ft1, ft8, dyn
  bext a0, t3, a1
  fwd_142:
  auipc s3, 0
  addi s3, s3, 36
  jalr a1, 0(s3)
  lui t2, 0
  csrrs s10, frm, zero
  remw a5, a5, t0
  orn a3, t2, s9
  xnor s8, s8, a1
  fcvt.lu.d a3, fs11, dyn
  fwd_143:
  beq zero, gp, . + 12
  fence.i
  clmul t1, s7, tp
  fwd_144:
  blt t2, a6, . + 20
  fcvt.wu.d t4, fs8, dyn
  sraiw s5, t4, 1
  lw zero, -940(t6)
  fcvt.s.l fs2, s3, dyn
  fwd_145:
  beq s2, t0, . + 28
  div a2, a2, s6
  csrrwi tp, sepc, 15
  fcvt.d.l ft3, s6, dyn
  rorw s8, a4, a4
  packh s4, a4, s8
  sraiw s8, s8, 31
  fwd_146:
  jal a7, . + 12
  binv s3, ra, s0
  fcvt.lu.d tp, fs8, dyn
  fwd_147:
.4byte 0x0000006b
.option rvc
write_tohost:
  la t1, tohost
  li t2, 0x1
  sw t2, 0(t1)
_exit:
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  nop
  j _exit
debug_rom:
  dret
debug_exception:
  dret
instr_end:
  nop
.section .data
.align 6
.global tohost
tohost:
.dword 0x0
.align 6
.global fromhost
fromhost:
.dword 0x0
.section .region_0, "aw", @progbits
region_0:
.word 0xbca86c83, 0x0000006f, 0xfffff000, 0xbf800000, 0x00000001, 0xff800000, 0x434d8cb9, 0x3ffbf25a
.section .mem_region, "aw", @progbits
.align 4
mem_region:
.zero 2048
.word 0x80000000, 0x80000000, 0x00000001, 0x40000000, 0xbd7cc7a5, 0x3dfc88da, 0x4116e5d3, 0x44e431e3
.word 0x7fc00000, 0xff800000, 0xff800000, 0x80000000, 0x00000001, 0xb67c5bca, 0x7f800001, 0xffff055f
.word 0x72b4c585, 0x00000080, 0x00800000, 0x00000000, 0x44468330, 0x443ed4a7, 0x9aca14ab, 0x00800000
.word 0xffffffff, 0xc289f9d2, 0xffff0f8b, 0xa12d7474, 0xffff085d, 0x00008000, 0xbf1c85f3, 0x00800000
.word 0x00000003, 0x8edb7173, 0xe8b3cdf3, 0x80000000, 0x00000996, 0x10606e37, 0x0000006f, 0x00000000
.word 0x00000000, 0x80000479, 0x00000100, 0xc67877a6, 0x0000048e, 0x7fc00000, 0x80000000, 0x7f800000
.word 0x2f82c435, 0x80808080, 0x7fc00000, 0x7fffffff, 0xffffffff, 0x7f7fffff, 0x01010101, 0x80000000
.word 0x00000100, 0x7f800000, 0xbb17825f, 0x7fc00000, 0xaaaaaaaa, 0xffffffff, 0x800007a0, 0x00007f61
.word 0x19f821e2, 0x00000000, 0x55555555, 0xffffffff, 0xfffff000, 0x7f7fffff, 0xc197a0e9, 0x01000000
.word 0x00000000, 0x00000000, 0xffffffff, 0x0000006f, 0x25e6ed59, 0x7fc00000, 0x5cc9bb01, 0x00010000
.word 0xff800000, 0x00000d10, 0x00000000, 0x00000001, 0x7f800001, 0xffffffff, 0x00000000, 0xffffffff
.word 0xffffffff, 0xc6037210, 0x00000001, 0xffffffff, 0x00000001, 0xae9197fa, 0x5d22c030, 0x7f7fffff
.word 0x55555555, 0x3d54e63a, 0x00000000, 0x0000006f, 0x40000000, 0x00000080, 0x7f800001, 0xc4266536
.word 0x0000006f, 0xffffffff, 0x00000001, 0x00800000, 0x4828e4fe, 0x80000004, 0xff800000, 0x0000006f
.word 0xbbfa6b88, 0x01000000, 0x7fffffff, 0xffffffff, 0x800001a3, 0x752c1b77, 0xbd917482, 0x80000b72
.word 0x7fc00000, 0x00000002, 0x0000006f, 0x814592e6, 0xc2833662, 0x00000003, 0x00800000, 0x00000000
.word 0x00000000, 0x80000000, 0xca8b8dd0, 0xff800000, 0x00000100, 0xfd10e072, 0xc2e2862b, 0x6f9a00e5
.word 0xc1e356d3, 0xc21c324c, 0xdf7fee49, 0x00000000, 0x7df9a9e3, 0xaecb78df, 0x80000000, 0x00000000
.word 0x1ceefe03, 0x87b7a8b9, 0xff800000, 0xffffffff, 0x01000000, 0x423604d6, 0x00000001, 0x00000001
.word 0x7fc00000, 0x00000000, 0xff800000, 0x7fffffff, 0xc4bc159c, 0x47312192, 0x7fc00000, 0x80000000
.word 0x44777c71, 0xc1dc1644, 0xbe4eeb59, 0x40000000, 0x00000002, 0x0000006f, 0x452f6c5c, 0x00000001
.word 0xbf800000, 0xaaaaaaaa, 0xbf800000, 0xbf800000, 0x01000000, 0x7fc00000, 0x0000006f, 0x7f800001
.word 0x04d61dff, 0x3c84c09e, 0x55555555, 0x00000001, 0x00008ad7, 0x7f7fffff, 0x00000002, 0x7be40698
.word 0x00000001, 0xade7e7ef, 0x80000000, 0x800001dd, 0x00000003, 0x7fc00000, 0xd44dd26f, 0x00000001
.word 0xc18dedbb, 0x00000000, 0x40000000, 0xff800000, 0x80000000, 0x80000000, 0x00000000, 0x7fc00000
.word 0x80000004, 0x507b25fc, 0x55555555, 0xffffffff, 0x800009ed, 0x0000006f, 0x00008e4c, 0x7f800001
.word 0x80000000, 0x7fc00000, 0x83fb35da, 0xffffffff, 0x00000000, 0xff800000, 0x7f7fffff, 0xffff0491
.word 0x00000001, 0xfffff000, 0xc5577915, 0x4701964d, 0xc516580d, 0x00000001, 0x00000001, 0x06782e5e
.word 0x46c9b23f, 0xbb6870c6, 0x00000000, 0x00000000, 0x7f800000, 0xff800000, 0xffff0ea3, 0xff800000
.word 0xffffffff, 0x7fc00000, 0x00ff00ff, 0xbf800000, 0x80000000, 0x0000006f, 0x7fc00000, 0x3f800000
.word 0xa177c317, 0xffeeb95a, 0xbf813bca, 0x9ba39b4e, 0x7fc00000, 0x7f7fffff, 0x80808080, 0x7f7fffff
.word 0x3daa7f53, 0x7f800000, 0x455a07d0, 0x80000000, 0xc57e40a6, 0xf85550f8, 0xff800000, 0x7fffffff
.word 0xbcda4fd6, 0xffff0668, 0x00ff00ff, 0xe2d7a24d, 0x0000006f, 0xbe3d29fd, 0xff800000, 0x80000000
.word 0x00008000, 0x00001000, 0x00000080, 0x80000f81, 0x00000080, 0x3ea1d93a, 0x3ed085aa, 0x80000000
.word 0x7fc00000, 0x00000000, 0x55555555, 0x00000000, 0x7f7fffff, 0x7fffffff, 0xbb38f7da, 0x00000be6
.word 0x7fffffff, 0x872a8816, 0x80000000, 0x3c49ae76, 0x7f800000, 0xff800000, 0x80000000, 0x00001000
.word 0xffff07b3, 0x00000001, 0x0000006f, 0x7fc00000, 0x00000002, 0x80000000, 0x00000000, 0x00000002
.word 0x3e7e3d32, 0xc5baf9cb, 0x00000100, 0xff800000, 0xff800000, 0x00000001, 0xaaaaaaaa, 0x00000000
.word 0x00000000, 0x7fc00000, 0x8000058f, 0x800009ff, 0x80808080, 0x3b2cd7f3, 0xda8a7086, 0xff800000
.word 0x80000000, 0x80000000, 0x832084f5, 0x55555555, 0x3c39f022, 0x0000006f, 0xc24428af, 0x7fc00000
.word 0xa234778a, 0x449cb467, 0x40000000, 0xff800000, 0x4fb62e67, 0x800008a0, 0x00000100, 0x7f800000
.word 0xbf6bb23f, 0x7f7fffff, 0xf1784216, 0x55555555, 0x7f800000, 0x80000004, 0x7fffffff, 0xff00ff00
.word 0x00000000, 0xe7904dd2, 0x40000000, 0xafd726ae, 0x80000000, 0x62dd5b9d, 0x00000000, 0x7fc00000
.word 0x80000000, 0x55555555, 0x80000004, 0x7f800000, 0x01000000, 0xf9bd93c3, 0xffffffff, 0x2ea686c3
.word 0x55555555, 0x80000000, 0x00000001, 0xff800000, 0x00000001, 0xc89445b0, 0x7fc00000, 0xc3a59e70
.word 0x7fc00000, 0x00000001, 0x0000006f, 0x00000000, 0x80000000, 0x45eaf328, 0x40000000, 0x00000100
.word 0xc7c0bd05, 0x00000001, 0x01010101, 0x7f800001, 0x00000080, 0xffffffff, 0xffffffff, 0x0000006f
.word 0x0000006f, 0xbd89ebdd, 0x2688a9f0, 0x80000000, 0x80000000, 0x80000000, 0xff800000, 0x80000000
.word 0xf97c079d, 0x00000080, 0x426bfff8, 0x517adc25, 0x00000001, 0xb41a0dae, 0x7f800001, 0x406c7ac2
.word 0x000089a5, 0x80000004, 0x7f7fffff, 0xffff0fe6, 0x01010101, 0x00008ecb, 0x1b7692b7, 0x00800000
.word 0x80000000, 0x00000000, 0x0591d789, 0x40000000, 0xffffffff, 0x7f7fffff, 0x4683149b, 0x47f70cf1
.word 0x7fc00000, 0x80000000, 0xc102ce45, 0x7fc00000, 0xac169950, 0x40b448ce, 0x00000000, 0x80000004
.word 0x6de2d667, 0x2ea07c55, 0x7fc00000, 0x45d9257e, 0x00000100, 0x01000000, 0xc2fb1a3f, 0x0000006f
.word 0x00000003, 0xef9024d9, 0x00007fc5, 0xff800000, 0x0000006f, 0x39461450, 0x7fffffff, 0x7f800001
.word 0x00000000, 0x7fc00000, 0x492510a4, 0xffffffff, 0x00000000, 0xc3de79da, 0x97c86a4e, 0x00000080
.word 0x80000000, 0x4541567b, 0x80808080, 0xffff05f5, 0x40000000, 0x7f800000, 0xc43e5144, 0xffffffff
.word 0x00000000, 0xffffffff, 0x01010101, 0x4784657c, 0x00000001, 0x43ac4519, 0xd95acf26, 0x47094017
.word 0x2dbb867d, 0x3f800000, 0x8000037b, 0x3e62fe00, 0x00000001, 0xf71c652c, 0xfad9e0ae, 0xbd4d4b34
.word 0x00000000, 0x01000000, 0xb43c5a17, 0xd2f65ac6, 0xffffffff, 0x419ed0e0, 0x00008000, 0x8f605b3e
.word 0xff800000, 0x3f800000, 0xffff01b8, 0x00000003, 0x00000000, 0xe41358a8, 0x80000000, 0xffffffff
.word 0x3f278f32, 0x7f7fffff, 0x0000006f, 0x00000100, 0x3c52ef6c, 0x800009fa, 0x00000000, 0x80000000
.word 0x00000001, 0x00000d7d, 0x843e0670, 0x9904861c, 0x80000000, 0x7fc00000, 0x00000080, 0x55555555
.word 0xff800000, 0x80000000, 0xbb3f23ec, 0x80000000, 0x00000001, 0x44e8e3b7, 0x0000006f, 0x00010000
.word 0x00000000, 0xbe53e3c8, 0x00000001, 0x00000001, 0x00000000, 0xc5eee3e9, 0x7f800000, 0x00000000
.word 0x3bc146b3, 0xbd095e02, 0x00000001, 0x00010000, 0xcddf0fe9, 0x00000001, 0x7fffffff, 0x00000001
.word 0xffffffff, 0x7ec7778d, 0x7fc00000, 0xff800000, 0x00000002, 0xaaaaaaaa, 0x00ff00ff, 0xff00ff00
.word 0x00000000, 0x44d429e1, 0x80000883, 0x7f800001, 0x7f800000, 0x00000080, 0x0000006f, 0x47f11373
.word 0x7f800000, 0x3017ff6e, 0x7f800001, 0xb3527fbe, 0x00010000, 0x7f800001, 0x00000080, 0x00000003
.word 0x80000000, 0x3f4f41fe, 0x00800000, 0xff00ff00, 0xffffffff, 0x00008000, 0x47c4621f, 0x00000001
.word 0x00000002, 0x00000002, 0x9ecd152e, 0x7f7fffff, 0x3f800000, 0x7fc00000, 0xffffffff, 0x7fc00000
.word 0x00008000, 0x57663dc5, 0xffffffff, 0xc3982ebe, 0x0000006f, 0x7f800000, 0x00000000, 0x40e55a08
.word 0x0d85d82c, 0x00000000, 0xffff0680, 0x89e3edbc, 0xffffffff, 0x80000000, 0x00007f9a, 0xbc2e6547
.word 0x00000001, 0x00000000, 0x01010101, 0x7f800001, 0x589341ef, 0x000003cf, 0x00000000, 0xbf800000
.word 0x7fc00000, 0x00001000, 0x00000000, 0x80000000, 0xbbcd387c, 0x3c2e9385, 0x7795df65, 0x423a26d3
.word 0x4105f6ec, 0x40000000, 0x80000000, 0xd3d3740c, 0x80000004, 0xffff0a6f, 0xbbcb77da, 0x0000006f
.word 0xbf25f586, 0x0000006f, 0x5c9730f2, 0x00800000, 0x3c2941bf, 0x4521ead7, 0x0000006f, 0x7fc00000
.word 0xc7078b97, 0xffffffff, 0x43e6a1bc, 0x3c6ebfa5, 0x7fc00000, 0xffffffff, 0x46611a52, 0x00000000
.word 0xffffffff, 0x40000000, 0x00000000, 0x40000000, 0x80000000, 0xff00ff00, 0x3f800000, 0xc3d6cf53
.word 0xffffffff, 0x00000edc, 0x00000000, 0x0000006f, 0x00800000, 0x01010101, 0x00000100, 0x00008000
.word 0x26061133, 0xff800000, 0x267ab0d9, 0x80808080, 0x80000000, 0x71c48f0b, 0xffffffff, 0x3b49dce6
.word 0x42158470, 0x00000001, 0x00000000, 0xbc7bee04, 0x80000000, 0x86de1461, 0x23840833, 0x0000006f
.word 0x80000000, 0xbbcbdc59, 0x6acb0e02, 0x264f3efa, 0xff800000, 0x55555555, 0xff800000, 0x00000001
.word 0xbb017759, 0x00000003, 0x00008000, 0x7fc00000, 0x00008267, 0xff800000, 0x00000000, 0x00000001
.word 0xff800000, 0x449af855, 0x80000000, 0x3f4e3c71, 0x80000000, 0x475966a6, 0x0000006f, 0x8c5f76d1
.word 0xff00ff00, 0x7f7fffff, 0x572d3c09, 0x3bd9cd44, 0x80000000, 0x41b94366, 0x00010000, 0x80000000
.word 0xc6e5a24c, 0x00000000, 0xb9487cfd, 0xaaaaaaaa, 0xff00ff00, 0x7f7fffff, 0x55555555, 0xbc7f1f0b
.word 0x80000000, 0x448e3f4a, 0x7f800000, 0xff800000, 0xc1b4229f, 0x7fc00000, 0x06c7d203, 0x7f800000
.word 0x0674a9ce, 0xc10f9970, 0xffffffff, 0x46b61ce6, 0x8cd497cd, 0xbe081e22, 0x5d190ebc, 0x00000002
.word 0x7f800000, 0x7f7fffff, 0x00ff00ff, 0xf507a127, 0x28edc49c, 0x00800000, 0x25d70484, 0x00000000
.word 0x9d022e90, 0x00000000, 0x7fc00000, 0x00000001, 0x80000000, 0x00000001, 0x00010000, 0x7f800000
.word 0xaaaaaaaa, 0xc75c5d63, 0x000008aa, 0x00000000, 0x80000000, 0xffffffff, 0x80000000, 0x00000080
.word 0x00000080, 0x00000000, 0x00ff00ff, 0x00000003, 0x4113035d, 0x00000000, 0xff800000, 0x3bfccf7d
.word 0xe450afa2, 0x80000000, 0xff800000, 0xa9c7058c, 0xff800000, 0x416a9493, 0xaaaaaaaa, 0x00000001
.word 0x7fc00000, 0xff800000, 0xc0129019, 0x3e935661, 0xc64c3754, 0xbf800000, 0x80000000, 0x4abf05d5
.word 0xbddb29d1, 0x7fc00000, 0x80808080, 0x456b0713, 0xffff0652, 0x80000004, 0xff800000, 0xffffffff
.word 0x00000000, 0x43ec60ed, 0x800007f3, 0xff800000, 0x0d93977c, 0x00000000, 0x00000001, 0x00010000
.word 0x80808080, 0x5cde9a8c, 0x00010000, 0x7f7fffff, 0x00000003, 0x80000000, 0x8000032a, 0x00000000
.word 0xc4877b54, 0x41a9bc99, 0xc74632a1, 0x0000006f, 0xffffffff, 0xa091e803, 0x00001000, 0x00000000
.word 0xff800000, 0x80000000, 0x271b638a, 0x7f7fffff, 0x00000100, 0xbf800000, 0x0000084a, 0x7f800000
.word 0xffffffff, 0x0000006f, 0x7fc00000, 0x00000000, 0xc20d8cf7, 0x00800000, 0x00000000, 0xc2ab4018
.word 0x9524beb2, 0xff800000, 0xff800000, 0x80000000, 0x0000006f, 0x00000100, 0x7fc00000, 0x00000000
.word 0xff800000, 0x3e3f07a7, 0xfb10bbe3, 0x55555555, 0xffffffff, 0x00000000, 0x1a281c73, 0x01000000
.word 0xc68bab83, 0xff800000, 0x00800000, 0x05e4eed5, 0xffff078d, 0x90160dc9, 0x80000000, 0x3f800000
.word 0x000086ee, 0x00000001, 0xff800000, 0xffff0968, 0xc028e620, 0xffff077c, 0xe1ab7f25, 0x00001000
.word 0x00000000, 0x80000000, 0x40000000, 0xff800000, 0xffffffff, 0x7f7fffff, 0x00010000, 0x7f7fffff
.word 0x00000000, 0x87cbf6f1, 0x00000002, 0x5baa514e, 0x477134f2, 0x80000000, 0x7fffffff, 0x7f800001
.word 0x44dda8bc, 0x7f800000, 0x00000000, 0xc948cac2, 0x7f800000, 0xff800000, 0x80000000, 0x7f7fffff
.word 0x80000004, 0x00000694, 0xff800000, 0x5a38322a, 0xaaaaaaaa, 0x80000000, 0x00001000, 0x0000006f
.word 0x5bf8472d, 0x00800000, 0xc56fd792, 0x00800000, 0x00001000, 0x98327d04, 0x80000000, 0x0000006f
.word 0xc130dbff, 0xd82373a6, 0x7fc00000, 0x7fffffff, 0x7fc00000, 0x3ed6cfae, 0x00008000, 0xc472fb46
.word 0x427506b8, 0xffffffff, 0x00800000, 0xa6aa0562, 0xc654e199, 0x00000000, 0xffffffff, 0x00000080
.word 0x3b3087c9, 0x7f7fffff, 0x27f18b34, 0xffff0777, 0x07f46f93, 0x00008000, 0xffffffff, 0x2ca9af20
.word 0x3f7e02f7, 0xbf800000, 0xffffffff, 0x7fc00000, 0x7fffffff, 0x00010000, 0x406df4d9, 0x0000006f
.word 0x7c68e7d4, 0xb032df25, 0x7fc00000, 0x7f800000, 0xffff0170, 0x80000000, 0x7f800000, 0x00000000
.word 0x80808080, 0xb778d788, 0x7f800001, 0x3c129ed4, 0x00000001, 0x00000d83, 0xffffffff, 0x0000006f
.word 0x40b7d841, 0xff800000, 0xfffff000, 0xc2843104, 0x00000080, 0x36eca6ef, 0x5a23f77b, 0x7f7fffff
.word 0xaaaaaaaa, 0x7f800000, 0x80000000, 0x00000003, 0x40000000, 0x0000006f, 0x00000001, 0x88caf4cb
.word 0x7f7fffff, 0x00000100, 0x80000000, 0x00000001, 0xc1c8f568, 0xffff07a6, 0x3f800000, 0x00000000
.word 0x6f4d3062, 0x00000000, 0x80000e2d, 0x00000001, 0xff800000, 0x80000004, 0xe1de09c9, 0x01000000
.word 0xff800000, 0x00000000, 0x0000006f, 0x7fc00000, 0x5fe038e9, 0x80000000, 0x7f800001, 0x7f800001
.word 0x7f800000, 0x7fc00000, 0x80000000, 0x800009b0, 0x00000001, 0x0000006f, 0x40000000, 0x3c26e9c9
.word 0x00010000, 0xdc935158, 0x7fc00000, 0x853966e9, 0x0000006f, 0x41542ce4, 0xce305810, 0x747e552e
.word 0x0d5a0483, 0x7fffffff, 0xbf800000, 0x7b3ffc04, 0x55555555, 0xfffff000, 0x00008000, 0x80000000
.word 0x40c4930f, 0x00000001, 0x01010101, 0x7f800000, 0x289914c2, 0x80000000, 0x80000000, 0xe14c24c0
.word 0xefb83327, 0x00000080, 0x00000002, 0x1194cdd3, 0x01000000, 0x2663b82d, 0x0000006f, 0x7f800001
.word 0x00000100, 0xffffffff, 0x00000100, 0xc2f48ab8, 0x7fffffff, 0x00008000, 0xfffff000, 0x0000006f
.word 0xffffffff, 0x00000001, 0x80000004, 0x00800000, 0xaaaaaaaa, 0x00000001, 0x80808080, 0xef6f40b9
.word 0x7f800000, 0x00000001, 0xffffffff, 0x80000000, 0x800000fc, 0xffff0bed, 0x7f800000, 0x8fafbcc1
.zero 2048
mem_region_end:
.section .stack_region, "aw", @progbits
.align 4
stack_region:
.word 0x7f800000, 0x3f800000, 0x43d1803c, 0xbf800000, 0x00000100, 0xffffffff, 0xff800000, 0xc0193f47
.word 0x418125b1, 0xffff0fe5, 0x00000100, 0x7fc00000, 0x00000001, 0x55555555, 0x4661fd8b, 0x7f800000
.word 0x00000000, 0xff800000, 0x94943b5e, 0x7fc00000, 0x00000000, 0x00000115, 0x00000001, 0x7f7fffff
.word 0x00000080, 0xffffffff, 0x0ab7739c, 0x80000925, 0x7f800000, 0xffffffff, 0x50daffa6, 0x80000000
.word 0x7f7fffff, 0x00000003, 0x7f800000, 0x375bd161, 0xffffffff, 0x00000000, 0x7f800000, 0x421dab98
.word 0xffff09ea, 0x00000002, 0x00000100, 0x0000006f, 0xbb427b1b, 0x00000001, 0x7fc00000, 0xffffffff
.word 0x00ff00ff, 0xffff0842, 0x7fc00000, 0x7fffffff, 0x00000a8c, 0x8000027f, 0xaf846a5c, 0x00800000
.word 0x80000991, 0x00008000, 0xffff0b87, 0x7fc00000, 0x42825bdf, 0x00000000, 0x00000000, 0x36980bd8
.word 0x00ff00ff, 0xa85d4566, 0xffffffff, 0x00800000, 0x433c1a2e, 0x80000000, 0x80000bb2, 0x00000080
.word 0x68b62f5e, 0x7fc00000, 0x80000000, 0x00000002, 0x00000001, 0x000080aa, 0xbf800000, 0x11825867
.word 0xffff053c, 0xffffffff, 0xffff0e0d, 0x47038d18, 0x00008000, 0x7f800000, 0x7f800001, 0xff800000
.word 0x0000006f, 0x77419e5a, 0xbcf099b9, 0xffffffff, 0xa0f38954, 0x7f800000, 0x0000006f, 0x949c73a2
.word 0x00000000, 0x00000100, 0x00000080, 0x464f4a25, 0xe2ed4145, 0xc34a6c63, 0x80000000, 0x3cddbe5d
.word 0x0000006f, 0x42dd1f77, 0x65d29bdc, 0xc4dd1654, 0xffffffff, 0x46281d7c, 0x40000000, 0x00000000
.word 0x00000632, 0xff800000, 0x00008000, 0x80000000, 0x37dc4344, 0x7f800001, 0x9c0ed868, 0x80000000
.word 0x80000004, 0x00000d96, 0x80000004, 0x00000100, 0x00000000, 0xbf800000, 0x7f800001, 0x80808080
.word 0xffffffff, 0xbc84581b, 0x80000000, 0x7f7fffff, 0xbb4e1ff6, 0xff800000, 0xffffffff, 0xc12dae22
.word 0xcd1e44c5, 0x00010000, 0xbb471f96, 0x80000004, 0x00000000, 0x80808080, 0xc6146952, 0x0000006f
.word 0x40beb37b, 0xffffffff, 0x00000000, 0x00000001, 0x00000000, 0xc460b0c0, 0x7f800000, 0x7f800000
.word 0x01000000, 0xffffffff, 0x467e304e, 0x42ee5336, 0x00001000, 0xffffffff, 0xffffffff, 0xbba267b9
.word 0x00000003, 0x00800000, 0x41627837, 0xc3c5e628, 0x00000001, 0x00800000, 0xffffffff, 0x7fc00000
.word 0xbf800000, 0xbc167621, 0x00000b7b, 0x00000001, 0x00000100, 0x00000535, 0xc1c7e07c, 0x00ff00ff
.word 0x7fc00000, 0x00000001, 0x22f21c21, 0x00800000, 0x3dda196c, 0x7f800001, 0xffffffff, 0x0000006f
.word 0x7f800000, 0x090208a5, 0xffffffff, 0x00000002, 0x0000006f, 0x47e477ed, 0x7fc00000, 0x80000000
.word 0x7fc00000, 0x00000000, 0x00000001, 0x80000004, 0x00008000, 0x80808080, 0x00ff00ff, 0x7fc00000
.word 0x7fffffff, 0x3f800000, 0x0000006f, 0xbd344a73, 0x80000000, 0xc7387664, 0x00008000, 0x3e4fbbc0
.word 0x7fc00000, 0x00000080, 0x00000080, 0x5992b26c, 0x7fc00000, 0x3f49f50b, 0x3cdcf0e8, 0x000086bd
.word 0xffffffff, 0x00000001, 0x7f7fffff, 0x01000000, 0x7f7fffff, 0x00000000, 0x00000100, 0x40000000
.word 0x00000000, 0x80000000, 0x00000000, 0xffffffff, 0x00800000, 0xc4a310c4, 0x80000000, 0x00008702
.word 0xffffffff, 0x7f800000, 0xbd6d3a88, 0xc27f577d, 0x7740ddfa, 0xffffffff, 0xffffffff, 0xffff094d
.word 0xc07ecac3, 0xffffffff, 0xbf800000, 0xffffffff, 0x4332a55a, 0xffffffff, 0x768abcae, 0x00000000
.word 0xc7adf6a7, 0x00010000, 0x7f7fffff, 0xff800000, 0xc4576dc0, 0x042abf94, 0x3e6ab466, 0x00000001
stack_region_end:
