#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
import re
import time
import wave

from typing import Optional, Sequence

from utils.ddi_utils import DDIModel, bytes_to_str, stream_reverse_search
from utils.seg_utils import ArticulationSegmentInfo, generate_articulation_seg, generate_seg, generate_transcription

start_encode = 'SND '.encode()
wav_params = (1, 2, 44100, 0, 'NONE', 'NONE')
window_size = 512


def escape_xsampa(xsampa: str) -> str:
    """Escapes xsampa to file name."""
    xsampa = xsampa.replace("Sil", "sil")  # Sil is a special case
    xsampa = (
        xsampa.replace("\\", "-")
        .replace("/", "~")
        .replace("?", "!")
        .replace(":", ";")
        .replace("<", "(")
        .replace(">", ")")
    )
    return xsampa


def unescape_xsampa(xsampa: str) -> str:
    """Unescapes xsampa from file name."""
    xsampa = (
        xsampa.replace("-", "\\")
        .replace("~", "/")
        .replace("!", "?")
        .replace(";", ":")
        .replace("(", "<")
        .replace(")", ">")
    )
    return xsampa


def parse_args(args: Sequence[str] = None):  # : list[str]
    # initialize parser
    parser = argparse.ArgumentParser()
    parser.add_argument('--src_path', required=True,
                        help='source ddi file path')
    parser.add_argument('--dst_path',
                        help='destination extract path, '
                        'default to be "./[name]/snd"')
    parser.add_argument('--gen_lab', action='store_true',
                        help='generate lab file')
    parser.add_argument('--gen_seg', action='store_true',
                        help='generate trans, seg, as files')
    parser.add_argument('--classify', action='store_true',
                        help="classify files with index")

    # parse args
    args_result = parser.parse_args(args)

    ddi_path: str = os.path.normpath(args_result.src_path)
    ddb_path: str = re.sub(r'\.ddi$', '.ddb', ddi_path)

    dst_path: str = args_result.dst_path

    if dst_path is None:
        dst_path = os.path.dirname(ddi_path) + '/snd'
    dst_path: str = os.path.normpath(dst_path)

    # make dirs
    if not os.path.exists(dst_path):
        os.makedirs(dst_path)

    gen_lab: bool = args_result.gen_lab
    gen_seg: bool = args_result.gen_seg
    use_classify: bool = args_result.classify

    return ddi_path, ddb_path, dst_path, use_classify, gen_lab, gen_seg


def create_file_name(phonemes: list[str], use_classify: bool, offset: int, pitch: float, dst_path: str, file_type: str, idx: Optional[int] = None):
    offset_hex = f'{offset:0>8x}'
    escaped_phonemes = [escape_xsampa(p) for p in phonemes]
    phonemes_len = len(phonemes)

    if pitch >= 0:
        pit_str = f"pit+{pitch:.2f}"
    else:
        pit_str = f"pit{pitch:.2f}"

    filename = ""

    phonemes_str = " ".join(escaped_phonemes)
    snd_group = ""
    if phonemes_len == 0:
        filename = f"unknown_{offset_hex}.{file_type}"
    else:
        if phonemes_len == 1:
            if phonemes[0] == "growl":
                snd_group = "growl"
            else:
                snd_group = "sta"
        elif phonemes_len == 2:
            snd_group = "art"
        elif phonemes_len == 3:
            snd_group = "tri"
        file_type_prefix = "lab" if file_type == "lab" else "wav"
        filename = f"{snd_group}/"
        if use_classify and idx is not None:
            idx += 1
            filename += f"{idx}/"
        filename += f"{file_type_prefix}/[{phonemes_str}]_{pit_str}_{offset_hex}.{file_type}"

    folder = os.path.dirname(filename)
    if folder != "":
        os.makedirs(os.path.join(dst_path, folder), exist_ok=True)

    return filename


def nsample2sec(nsample: int, sample_rate: int) -> float:
    return nsample / sample_rate / 2


def frm2sec(frm: int, sample_rate: int) -> float:
    return frm * window_size / sample_rate / 2


def generate_art_lab(phonemes: list[str], frame_align: list[dict], sample_rate: int, offset_bytes: int, total_bytes: int):
    offset_time = nsample2sec(offset_bytes, sample_rate) * 1e7
    duration_time = nsample2sec(total_bytes, sample_rate) * 1e7
    lab_lines = []
    if len(phonemes) == 3:  # VCV
        center_phoneme = re.sub("^\^", "", phonemes[1])
        phonemes = [phonemes[0], center_phoneme, center_phoneme, phonemes[2]]

    lab_lines.append(f"0 {offset_time:.0f} sil")
    last_time = 0
    for i, phoneme in enumerate(phonemes):
        frame = frame_align[i]
        start_time = offset_time + frm2sec(frame["start"], sample_rate) * 1e7
        end_time = offset_time + frm2sec(frame["end"], sample_rate) * 1e7
        lab_lines.append(f'{start_time:.0f} {end_time:.0f} {phoneme}')
        last_time = end_time
    lab_lines.append(f'{last_time:.0f} {duration_time:.0f} sil')

    return "\n".join(lab_lines)


def generate_sta_lab(phoneme: str, sample_rate: int, offset_bytes: int, cutoff_bytes: int, total_bytes: int):
    offset_time = nsample2sec(offset_bytes, sample_rate) * 1e7
    cutoff_time = nsample2sec(cutoff_bytes, sample_rate) * 1e7
    duration_time = nsample2sec(total_bytes, sample_rate) * 1e7
    lab_lines = []

    lab_lines.append(f"0 {offset_time:.0f} sil")
    lab_lines.append(f"{offset_time:.0f} {cutoff_time:.0f} {phoneme}")
    lab_lines.append(f"{cutoff_time:.0f} {duration_time:.0f} sil")

    return "\n".join(lab_lines)


def generate_art_seg_files(
        phonemes: list[str], frame_align: list[dict], sample_rate: int, offset_bytes: int, total_bytes: int, unvoiced_consonant_list: list[str]):
    offset_time = nsample2sec(offset_bytes, sample_rate)
    duration_time = nsample2sec(total_bytes, sample_rate)

    boundary_chunks = 0
    if len(phonemes) == 3:  # VCV
        center_phoneme = re.sub("^\^", "", phonemes[1])
        phonemes = [phonemes[0], center_phoneme, phonemes[2]]
        boundary_chunks = 4
    else:
        boundary_chunks = 2

    boundaries: list[float] = []
    for i in range(0, boundary_chunks):
        start_time = offset_time + \
            frm2sec(frame_align[i]["start"], sample_rate)
        end_time = offset_time + frm2sec(frame_align[i]["end"], sample_rate)

        if i == 0:
            boundaries.append(start_time)
        boundaries.append(end_time)

    seg_list: list[list] = []
    
    if len(phonemes) == 3:
        seg_list.append([phonemes[0], boundaries[0], boundaries[1]])
        seg_list.append([phonemes[1], boundaries[1], boundaries[3]])
        seg_list.append([phonemes[2], boundaries[3], boundaries[4]])
    else:
        seg_list.append([phonemes[0], boundaries[0], boundaries[1]])
        seg_list.append([phonemes[1], boundaries[1], boundaries[2]])

    art_seg_info: ArticulationSegmentInfo = {
        "boundaries": boundaries,
        "phonemes": phonemes,
    }

    trans_content = generate_transcription(seg_list)
    seg_content = generate_seg(seg_list, duration_time)
    art_seg_content = generate_articulation_seg(
        art_seg_info, total_bytes, unvoiced_consonant_list)

    return trans_content, seg_content, art_seg_content


def generate_sta_seg_files(
        phoneme: str, sample_rate: int, offset_bytes: int, cutoff_bytes: int, total_bytes: int):
    offset_time = nsample2sec(offset_bytes, sample_rate)
    cutoff_time = nsample2sec(cutoff_bytes, sample_rate)
    duration_time = nsample2sec(total_bytes, sample_rate)

    seg_list: list[list] = [[phoneme, offset_time, cutoff_time]]

    trans_content = generate_transcription(seg_list)
    seg_content = generate_seg(seg_list, duration_time, "unknown")

    return trans_content, seg_content


def main():
    ddi_path, ddb_path, dst_path, use_classify, gen_lab, gen_seg = parse_args()

    snd_pos_list: list[int] = []

    # Read DDI file
    print("Reading DDI...")

    with open(ddi_path, "rb") as f:
        ddi_bytes = f.read()
        ddi_model = DDIModel(ddi_bytes)
        ddi_model.read()

    # Extract snd files from DDB
    ddb_size = os.path.getsize(ddb_path)
    with open(ddb_path, "rb") as ddb_f:
        # Dump articulation
        art_list: list[tuple[int, list, dict]] = []

        for art_item in ddi_model.art_data.values():
            if "artu" in art_item.keys():  # Triphoneme
                for artu_item in art_item["artu"].values():
                    i = 0
                    phonemes = [art_item["phoneme"],
                                artu_item["phoneme"]]
                    for artp_item in artu_item["artp"].values():
                        art_list.append((i, phonemes, artp_item))
                        i += 1
            if "art" in art_item.keys():
                for sub_art in art_item["art"].values():
                    if "artu" in sub_art.keys():
                        i = 0
                        for artu_item in sub_art["artu"].values():
                            phonemes = [art_item["phoneme"],
                                        sub_art["phoneme"],
                                        artu_item["phoneme"]]
                            print("Triphoneme:", phonemes)
                            for artp_item in artu_item["artp"].values():
                                print("triphoneme", phonemes)
                                art_list.append((i, phonemes, artp_item))
                                i += 1

        for art_item in art_list:
            idx = art_item[0]
            phonemes = art_item[1]
            art_item = art_item[2]

            _, t = art_item["snd"].split("=")
            snd_offset, _ = t.split("_")
            snd_offset = int(snd_offset, 16)

            pitch = art_item["pitch1"]

            output_path = os.path.join(dst_path, create_file_name(
                phonemes, use_classify, snd_offset, pitch, dst_path, "wav", idx))

            ddb_f.seek(snd_offset)
            snd_ident = ddb_f.read(4)
            if snd_ident != start_encode:
                print(
                    f'Error: SND header not found for articulation [{" ".join(phonemes)}] {i}')
                continue

            # Read snd header
            snd_length = int.from_bytes(ddb_f.read(4), byteorder='little')
            snd_frame_rate = int.from_bytes(ddb_f.read(4), byteorder='little')
            snd_channel = int.from_bytes(ddb_f.read(2), byteorder='little')
            int.from_bytes(ddb_f.read(4), byteorder='little')  # unknown

            snd_bytes = ddb_f.read(snd_length - 18)

            wav_params = (snd_channel, 2, snd_frame_rate, 0, 'NONE', 'NONE')

            # Write snd to wave file
            with wave.open(output_path, "wb") as wav_f:
                wav_f.setparams(wav_params)
                wav_f.writeframes(snd_bytes)

            print("Dumped [%s] -> %s" % (" ".join(phonemes), output_path))
            snd_pos_list.append(snd_offset)

            if (gen_lab or gen_seg) and art_item.get("frame_align"):
                _, t = art_item["snd_start"].split("=")
                snd_vstart_offset, _ = t.split("_")
                snd_vstart_offset = int(snd_vstart_offset, 16)

                snd_empt_bytes = snd_vstart_offset - snd_offset

                if gen_lab:
                    lab_content = generate_art_lab(
                        phonemes, art_item["frame_align"], snd_frame_rate, snd_empt_bytes, snd_length)
                    lab_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, use_classify, snd_offset, pitch, dst_path, "lab", idx))
                    with open(lab_output_path, "w") as lab_f:
                        lab_f.write(lab_content)
                elif gen_seg:
                    unvoiced_consonant_list = ddi_model.phdc_data["phoneme"]["unvoiced"]
                    trans_content, seg_content, art_seg_content = generate_art_seg_files(
                        phonemes, art_item["frame_align"], snd_frame_rate, snd_empt_bytes,
                        snd_length, unvoiced_consonant_list
                    )

                    trans_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, use_classify, snd_offset, pitch, dst_path, "trans", idx))
                    seg_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, use_classify, snd_offset, pitch, dst_path, "seg", idx))
                    art_seg_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, use_classify, snd_offset, pitch, dst_path, "as0", idx))

                    with open(trans_output_path, "w") as fp:
                        fp.write(trans_content)
                    with open(seg_output_path, "w") as fp:
                        fp.write(seg_content)
                    with open(art_seg_output_path, "w") as fp:
                        fp.write(art_seg_content)

        # Dump stationary
        for sta_info in ddi_model.sta_data.values():
            phoneme = sta_info["phoneme"]
            i = 0
            for sta_idx, sta_item in sta_info["stap"].items():
                _, snd_name = sta_item["snd"].split("=")
                snd_offset, snd_id = snd_name.split("_")

                snd_offset = int(snd_offset, 16)

                pitch = sta_item["pitch1"]

                output_path = os.path.join(dst_path, create_file_name(
                    [phoneme], use_classify, snd_offset, pitch, dst_path, "wav", i))

                # real_snd_offset = 0x3d
                real_snd_offset = stream_reverse_search(
                    ddb_f, b"SND ", snd_offset, 0x8000)
                if real_snd_offset == -1:
                    print(
                        f'Error: Cannot found SND for stationary [{phoneme}] {sta_idx}')
                    continue

                ddb_f.seek(real_snd_offset + 4)  # skip identificator

                # Read snd header
                snd_length = int.from_bytes(ddb_f.read(4), byteorder='little')
                snd_frame_rate = int.from_bytes(
                    ddb_f.read(4), byteorder='little')
                snd_channel = int.from_bytes(ddb_f.read(2), byteorder='little')
                int.from_bytes(ddb_f.read(4), byteorder='little')  # unknown

                snd_bytes = ddb_f.read(snd_length - 18)

                wav_params = (snd_channel, 2, snd_frame_rate,
                              0, 'NONE', 'NONE')

                # Write snd to wave file
                with wave.open(output_path, "wb") as wav_f:
                    wav_f.setparams(wav_params)
                    wav_f.writeframes(snd_bytes)

                if gen_lab or gen_seg:
                    offset_pos = snd_offset - real_snd_offset
                    cutoff_pos = sta_item["snd_length"] - offset_pos

                    if gen_lab:
                        lab_content = generate_sta_lab(
                            phoneme, snd_frame_rate, offset_pos, cutoff_pos, snd_length)
                        lab_output_path = os.path.join(dst_path, create_file_name(
                            [phoneme], use_classify, snd_offset, pitch, dst_path, "lab", i))
                        with open(lab_output_path, "w") as lab_f:
                            lab_f.write(lab_content)
                    elif gen_seg:
                        trans_content, seg_content = generate_sta_seg_files(
                            phoneme, snd_frame_rate, offset_pos, cutoff_pos, snd_length)

                        trans_output_path = os.path.join(dst_path, create_file_name(
                            [phoneme], use_classify, snd_offset, pitch, dst_path, "trans", i))
                        seg_output_path = os.path.join(dst_path, create_file_name(
                            [phoneme], use_classify, snd_offset, pitch, dst_path, "seg", i))

                        with open(trans_output_path, "w") as fp:
                            fp.write(trans_content)
                        with open(seg_output_path, "w") as fp:
                            fp.write(seg_content)

                print("Dumped [%s] -> %s" % (phoneme, output_path))
                snd_pos_list.append(real_snd_offset)

                i += 1

        # Dump VQM
        if "vqm" in ddi_model.ddi_data_dict:
            for vqm_idx, vqm_info in ddi_model.vqm_data.items():
                _, snd_name = vqm_info["snd"].split("=")
                snd_offset, snd_id = snd_name.split("_")

                snd_offset = int(snd_offset, 16)
                snd_id = int(snd_id, 16)
                pitch = vqm_info["pitch1"]

                output_path = os.path.join(dst_path, create_file_name(
                    ["growl"], use_classify, snd_offset, pitch, dst_path, "wav"))
                ddb_f.seek(snd_offset)

                # Read snd identificator
                snd_ident = ddb_f.read(4)
                if snd_ident != start_encode:
                    print(f'Error: SND header not found for VQM {vqm_idx}')
                    continue

                # Read snd header
                snd_length = int.from_bytes(ddb_f.read(4), byteorder='little')
                snd_frame_rate = int.from_bytes(
                    ddb_f.read(4), byteorder='little')
                snd_channel = int.from_bytes(ddb_f.read(2), byteorder='little')
                int.from_bytes(ddb_f.read(4), byteorder='little')  # unknown

                snd_bytes = ddb_f.read(snd_length - 18)

                wav_params = (snd_channel, 2, snd_frame_rate,
                              0, 'NONE', 'NONE')

                # Write snd to wave file
                with wave.open(output_path, "wb") as wav_f:
                    wav_f.setparams(wav_params)
                    wav_f.writeframes(snd_bytes)

                print("Dumped VQM growl -> %s" % (output_path))
                snd_pos_list.append(snd_offset)

        # Dump unindexed snd
        print("Scan for unindexed SND...")
        print("You can press Ctrl+C to stop scanning and keep the found SNDs.")

        buffer_len = 10240
        ddb_f.seek(0)
        progress_updated_time = 0

        try:
            while ddb_f.readable():
                buffer_offset = ddb_f.tell()
                buffer = ddb_f.read(buffer_len)

                if not buffer:
                    break

                for i in range(0, len(buffer)):
                    if buffer[i:i+4] == start_encode:
                        # Update progress bar
                        if time.time() - progress_updated_time > 0.5:
                            progress_updated_time = time.time()
                            print(
                                f'Progress: {ddb_f.tell() / ddb_size * 100:.2f}%', end='\r')

                        # Found SND header
                        snd_offset = buffer_offset + i

                        output_path = os.path.join(dst_path, create_file_name(
                            [], use_classify, snd_offset, 0, dst_path, "wav"))

                        ddb_f.seek(snd_offset + 4)  # skip identificator

                        # Read snd header
                        snd_length = int.from_bytes(
                            ddb_f.read(4), byteorder='little')
                        snd_frame_rate = int.from_bytes(
                            ddb_f.read(4), byteorder='little')
                        snd_channel = int.from_bytes(
                            ddb_f.read(2), byteorder='little')
                        int.from_bytes(ddb_f.read(
                            4), byteorder='little')  # unknown

                        if snd_offset in snd_pos_list:  # Already dumped
                            print("Skip dumped SND -> %s" % (output_path))
                            continue

                        snd_bytes = ddb_f.read(snd_length - 18)

                        wav_params = (snd_channel, 2,
                                      snd_frame_rate, 0, 'NONE', 'NONE')

                        # Write snd to wave file
                        with wave.open(output_path, "wb") as wav_f:
                            wav_f.setparams(wav_params)
                            wav_f.writeframes(snd_bytes)

                        print("Dumped unindexed SND -> %s" % (output_path))

                if len(buffer) < buffer_len:
                    break

                ddb_f.seek(buffer_offset + buffer_len - 4)
            print(f'Progress: 100%')
        except KeyboardInterrupt:
            print("Scanning aborted")

    print("Done")


if __name__ == '__main__':
    main()
