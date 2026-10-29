import math

# 実装(2026-10-29): IPU の簡略 IDCT 用の余弦テーブル (8x8、標準形)
_COS = [[math.cos((2 * x + 1) * u * math.pi / 16) for x in range(8)] for u in range(8)]
_C = [1 / math.sqrt(2)] + [1.0] * 7  # C(0)=1/sqrt(2), C(u>0)=1


class GraphicSynthesizer:
    def __init__(self):
        self.memory = [0] * (4 * 1024 * 1024)  # 4MB DRAM
        self.clock_speed = 150 * 10**6  # 150 MHz
        self.pixel_engines = 16
        self.width = 640
        self.height = 448
        self.frame_count = 0

    def render_frame(self):
        # 実装(2026-10-29): memory の先頭を 640x448 x 1byte のフレームバッファとみなす
        # 簡略モデル (286,720 entries <= 4MB)。非ゼロピクセル数とチェックサムを返す
        framebuffer_size = self.width * self.height
        nonzero = 0
        checksum = 0
        for value in self.memory[:framebuffer_size]:
            if value != 0:
                nonzero += 1
            checksum = (checksum + value) & 0xFFFFFFFF
        self.frame_count += 1
        return {
            "frame": self.frame_count,
            "nonzero_pixels": nonzero,
            "checksum": checksum,
            "pixels_per_engine": framebuffer_size // self.pixel_engines,
        }

class VPU:
    def __init__(self, id):
        self.id = id
        self.scratchpad_memory = [0] * (16 * 1024)  # 16KB SPR
        self.dma_channel = DMAChannel()
        self.mac_scale = 1  # broadcast scalar for the multiply-accumulate
        self.processed_vectors = 0

    def process_data(self, data):
        # 実装(2026-10-29): VU 風の簡略モデル (Emulation-CPU-by-GPU の要素演算ループが手本)。
        # data を 128bit = 4要素のベクトル単位で処理し、各要素を mac_scale 倍して
        # scratchpad 先頭4要素のアキュムレータへ累積する (multiply-accumulate)。
        # 結果はグループごとに scratchpad の 4要素目以降へも記録し、アキュムレータの
        # スナップショット一覧を返す。末尾の端数グループは 0 で埋めて処理する
        results = []
        data = list(data)
        for start in range(0, len(data), 4):
            group = (data[start:start + 4] + [0, 0, 0, 0])[:4]
            for i in range(4):
                self.scratchpad_memory[i] += group[i] * self.mac_scale
            snapshot = list(self.scratchpad_memory[:4])
            offset = 4 + self.processed_vectors * 4
            for i in range(4):
                self.scratchpad_memory[(offset + i) % len(self.scratchpad_memory)] = snapshot[i]
            results.append(snapshot)
            self.processed_vectors += 1
        return results

class DMAChannel:
    def __init__(self):
        self.buffer = []
        self.transferred_count = 0

    def transfer(self, data):
        # DMA transfer logic
        self.buffer.append(data)
        self.transferred_count += 1

class EmotionEngine:
    def __init__(self):
        self.vpu0 = VPU(0)
        self.vpu1 = VPU(1)
        self.ipu = IPU()
        # 実装(2026-10-29): CELL-processing-emulation の PPE (レジスタ/PC/メモリ) が手本
        self.registers = [0] * 32  # 32 general purpose registers
        self.pc = 0                 # program counter
        self.memory = [0] * 1024    # main memory (model)
        self.cycles = 0
        self.clock_speed = 294_912_000  # 294.912 MHz

    def execute_instruction(self, instruction):
        # 実装(2026-10-29): タプル形式の小命令セットを実行する簡略モデル。
        # ("MOVI", rd, imm) / ("ADD"|"SUB"|"MUL", rd, rs, rt) /
        # ("LOAD", rd, addr) / ("STORE", rs, addr) / ("VMAC", vpu_id, data) / ("NOP",)
        # 1命令ごとに pc と cycles が 1 進む。未知のオペコードは ValueError
        if not isinstance(instruction, tuple) or not instruction:
            raise ValueError(f"Invalid instruction: {instruction!r}")
        opcode = instruction[0]
        result = None
        if opcode == "NOP":
            pass
        elif opcode == "MOVI":
            _, rd, imm = instruction
            self.registers[rd] = imm
        elif opcode == "ADD":
            _, rd, rs, rt = instruction
            self.registers[rd] = self.registers[rs] + self.registers[rt]
        elif opcode == "SUB":
            _, rd, rs, rt = instruction
            self.registers[rd] = self.registers[rs] - self.registers[rt]
        elif opcode == "MUL":
            _, rd, rs, rt = instruction
            self.registers[rd] = self.registers[rs] * self.registers[rt]
        elif opcode == "LOAD":
            _, rd, addr = instruction
            self.registers[rd] = self.memory[addr]
        elif opcode == "STORE":
            _, rs, addr = instruction
            self.memory[addr] = self.registers[rs]
        elif opcode == "VMAC":
            _, vpu_id, data = instruction
            vpu = self.vpu0 if vpu_id == 0 else self.vpu1
            result = vpu.process_data(data)
        else:
            raise ValueError(f"Unknown opcode: {opcode!r}")
        self.pc += 1
        self.cycles += 1
        return result

class IPU:
    def __init__(self):
        self.local_buffer_memory = [0] * 128  # Local buffer
        self.blocks_decoded = 0

    def decode_mpeg2(self, data):
        # 実装(2026-10-29): 簡略モデル。これは MPEG-2 ビットストリームのデコーダでは
        # ない (ハフマン復号・量子化テーブル解析は行わない)。入力バイト列を 8x8 ブロックの
        # DCT 係数とみなし、標準形の逆 DCT を適用するだけのモデル
        # (furie-data-compress-algorithm の周波数領域処理が背景)。
        # 末尾は 0 で埋め、結果は local_buffer_memory へラップしながら累積する。
        # 戻り値は処理したブロック数
        data = bytes(data)
        blocks = 0
        for start in range(0, len(data), 64):
            block = list(data[start:start + 64]) + [0] * (64 - len(data[start:start + 64]))
            base = (blocks * 64) % len(self.local_buffer_memory)
            index = 0
            for y in range(8):
                for x in range(8):
                    total = 0.0
                    for v in range(8):
                        for u in range(8):
                            total += _C[u] * _C[v] * block[v * 8 + u] * _COS[u][x] * _COS[v][y]
                    self.local_buffer_memory[(base + index) % len(self.local_buffer_memory)] += total / 4
                    index += 1
            blocks += 1
        self.blocks_decoded += blocks
        return blocks

class PS2Emulator:
    def __init__(self):
        self.ee = EmotionEngine()
        self.gs = GraphicSynthesizer()

    def run(self, frames=3):
        # 実装(2026-10-29): 無限ループだった run() を、組み込みデモを一通り実行して
        # 戻る形に変更 (CELL-processing-emulation の fetch/execute デモ、
        # CPU-change-clocks-logic のステージ別ログ出力が手本)
        print("[EE] running built-in program")
        program = [
            ("MOVI", 1, 40),
            ("MOVI", 2, 2),
            ("ADD", 3, 1, 2),        # r3 = 42
            ("STORE", 3, 0),         # memory[0] = 42
            ("LOAD", 4, 0),          # r4 = 42
            ("MUL", 5, 4, 2),        # r5 = 84
            ("SUB", 6, 5, 1),        # r6 = 44
            ("VMAC", 1, [1, 1, 1, 1]),  # delegate one vector op to VPU1
            ("NOP",),
        ]
        for instruction in program:
            self.ee.execute_instruction(instruction)
        print(f"[EE] done: pc={self.ee.pc}, cycles={self.ee.cycles}, "
              f"r3={self.ee.registers[3]}, r5={self.ee.registers[5]}, r6={self.ee.registers[6]}")

        print("[DMA/VPU] transferring sample vectors to VPU0")
        samples = [1, 2, 3, 4, 5, 6, 7, 8]
        self.ee.vpu0.dma_channel.transfer(samples)
        results = self.ee.vpu0.process_data(self.ee.vpu0.dma_channel.buffer[-1])
        print(f"[DMA/VPU] transfers={self.ee.vpu0.dma_channel.transferred_count}, "
              f"vectors={self.ee.vpu0.processed_vectors}, accumulator={results[-1]}")

        print("[IPU] decoding sample blocks (simplified IDCT model)")
        sample_stream = bytes([64] + [0] * 63 + [32] + [0] * 63)
        blocks = self.ee.ipu.decode_mpeg2(sample_stream)
        print(f"[IPU] blocks decoded: {blocks}, buffer[0]={self.ee.ipu.local_buffer_memory[0]:.1f}")

        print("[GS] writing test pattern and rendering frames")
        for i in range(100):
            self.gs.memory[i] = 255
        self.gs.memory[1000] = 128
        stats = None
        for _ in range(frames):
            stats = self.gs.render_frame()
            print(f"[GS] frame {stats['frame']}: nonzero={stats['nonzero_pixels']}, checksum={stats['checksum']}")

        print("[PS2] demo complete")
        return {
            "ee_cycles": self.ee.cycles,
            "vpu0_vectors": self.ee.vpu0.processed_vectors,
            "ipu_blocks": blocks,
            "gs_frames": self.gs.frame_count,
            "gs_last_stats": stats,
        }

if __name__ == "__main__":
    emulator = PS2Emulator()
    emulator.run()
