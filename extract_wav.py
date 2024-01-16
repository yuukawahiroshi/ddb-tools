#!/usr/bin/env python3
from __future__ import annotations
import argparse
import math
import os
import re
import time
import wave

from typing import Sequence, TypedDict

from utils.ddi_utils import DDIModel, bytes_to_str, stream_reverse_search

start_encode = 'SND '.encode()
wav_params = (1, 2, 44100, 0, 'NONE', 'NONE')
window_size = 512


class ArticulationSegmentInfo(TypedDict):
    phonemes: list[str, str]
    boundaries: list[list[str, float, float]]


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
    parser.add_argument('--gen_lab', type=bool, default=False,
                        help='generate lab file')
    parser.add_argument('--gen_seg', type=bool, default=False,
                        help='generate trans, seg, as files')
    parser.add_argument('--filename_style',
                        type=str, choices=['flat', 'devkit'], default=None,
                        help="output filename style, default to be 'devkit', or default to be 'flat' if gen_lab is true.")

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
    filename_style: str = args_result.filename_style

    if filename_style is None:
        if gen_lab or gen_seg:
            filename_style = "flat"
        else:
            filename_style = "devkit"

    return ddi_path, ddb_path, dst_path, filename_style, gen_lab, gen_seg


def create_file_name(phonemes: list[str], name_style: str, offset: int, pitch: float, dst_path: str, file_type: str):
    offset_hex = f'{offset:0>8x}'
    escaped_phonemes = [escape_xsampa(p) for p in phonemes]
    phonemes_len = len(phonemes)

    if pitch >= 0:
        pit_str = f"pit+{pitch:.2f}"
    else:
        pit_str = f"pit{pitch:.2f}"

    filename = ""

    if name_style == "flat":
        phonemes_str = "-".join(escaped_phonemes)
        prefix = ""
        if phonemes_len == 0:
            filename = f"unknown_{offset_hex}.{file_type}"
        else:
            if phonemes_len == 1:
                if phonemes[0] == "growl":
                    prefix = "growl"
                else:
                    prefix = "sta"
            elif phonemes_len == 2:
                prefix = "art"
            elif phonemes_len == 3:
                prefix = "tri"
            file_type_prefix = "lab" if file_type == "lab" else "wav"
            filename = f"{file_type_prefix}/{prefix}_[{phonemes_str}]_{pit_str}_{offset_hex}.{file_type}"
    elif name_style == "devkit":
        phonemes_path = "/".join([item + "#" + bytes_to_str(item.encode('utf-8'))
                                 for item in escaped_phonemes])
        root_path = ""
        if phonemes_len == 0:
            filename = f"unknown/{offset_hex}.{file_type}"
        else:
            if phonemes_len == 1:
                if phonemes[0] == "growl":
                    root_path = "vqm/growl"
                else:
                    root_path = "stationary"
            elif phonemes_len == 2:
                root_path = "articulation"
            elif phonemes_len == 3:
                root_path = "triphoneme"
            filename = f"{root_path}/{phonemes_path}/{pit_str}_{offset_hex}.{file_type}"

    folder = os.path.dirname(filename)
    if folder != "":
        os.makedirs(os.path.join(dst_path, folder), exist_ok=True)

    return filename


def nsample2sec(nsample: int, sample_rate: int) -> float:
    return nsample / sample_rate / 2


def frm2sec(frm: int, sample_rate: int) -> float:
    return frm * window_size / sample_rate / 2


def generate_lab(phonemes: list[str], frame_align: list[dict], sample_rate: int, offset_bytes: int, total_bytes: int):
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


def generate_seg_files(
        phonemes: list[str], frame_align: list[dict], sample_rate: int, offset_bytes: int, total_bytes: int, unvoiced_consonant_list: list[str]):
    offset_time = nsample2sec(offset_bytes, sample_rate)
    duration_time = nsample2sec(total_bytes, sample_rate)

    if len(phonemes) == 3:  # VCV
        center_phoneme = re.sub("^\^", "", phonemes[1])
        phonemes = [phonemes[0], center_phoneme, center_phoneme, phonemes[2]]

    seg_list: list[list] = []
    boundaries: list[float] = []
    for i, phoneme in enumerate(phonemes):
        start_time = offset_time + \
            frm2sec(frame_align[i]["start"], sample_rate)
        end_time = offset_time + frm2sec(frame_align[i]["end"], sample_rate)

        if i == 0:
            boundaries.append(start_time)
        boundaries.append(end_time)

        seg_list.append([phoneme, start_time, end_time])

    art_seg_info: ArticulationSegmentInfo = {
        "boundaries": boundaries,
        "phonemes": []
    }

    if len(phonemes) == 4:  # VCV
        art_seg_info["phonemes"] = [phonemes[0], phonemes[1], phonemes[3]]
    else:
        art_seg_info["phonemes"] = phonemes

    trans_content = generate_transcription(seg_list)
    seg_content = generate_seg(seg_list, duration_time)
    art_seg_content = generate_articulation_seg(
        art_seg_info, total_bytes, unvoiced_consonant_list)

    return trans_content, seg_content, art_seg_content


def generate_transcription(seg_info: list[list]) -> str:
    content = []

    phoneme_list = []
    for i in range(0, len(seg_info)):
        phoneme_list.append(seg_info[i][0])

    content.append(" ".join(phoneme_list))

    trans_group = [item[0] for item in seg_info]
    content.append("[" + " ".join(trans_group) + "]")

    return "\n".join(content)


def generate_seg(
    phoneme_list: list[list], wav_length: float
) -> str:
    content = [
        "nPhonemes %d" % (len(phoneme_list) + 2,),  # Add 2 Sil
        "articulationsAreStationaries = 0",
        "phoneme		BeginTime		EndTime",
        "===================================================",
    ]

    content.append("%s\t\t%.6f\t\t%.6f" % ("Sil", 0, phoneme_list[0][1]))

    begin_time: float = 0
    end_time: float = 0
    for i in range(0, len(phoneme_list)):
        phoneme_info = phoneme_list[i]
        phoneme_name = phoneme_info[0]
        begin_time = phoneme_info[1]
        end_time = phoneme_info[2]

        content.append("%s\t\t%.6f\t\t%.6f" %
                       (phoneme_name, begin_time, end_time))

    content.append("%s\t\t%.6f\t\t%.6f" % ("Sil", end_time, wav_length))

    return "\n".join(content) + "\n"


def generate_articulation_seg(
    art_seg_info: ArticulationSegmentInfo, wav_samples: int, unvoiced_consonant_list: list[str]
) -> str:
    content = [
        "nphone art segmentation",
        "{",
        '\tphns: ["' + ('", "'.join(art_seg_info["phonemes"])) + '"];',
        "\tcut offset: 0;",
        "\tcut length: %d;" % int(math.floor(wav_samples / 2)),
    ]

    boundaries_str = [
        ("%.9f" % item) for item in art_seg_info["boundaries"]
    ]
    content.append("\tboundaries: [" + ", ".join(boundaries_str) + "];")

    content.append("\trevised: false;")

    voiced_str = []
    is_triphoneme = len(art_seg_info["phonemes"]) == 3
    for i in range(0, len(art_seg_info["phonemes"])):
        phoneme = art_seg_info["phonemes"][i]
        is_unvoiced = phoneme in unvoiced_consonant_list or phoneme in [
            "Sil",
            "Asp",
            "?",
        ]
        voiced_str.append(str(not is_unvoiced).lower())
        if is_triphoneme and i == 1:  # Triphoneme needs 2 flags for center phoneme
            voiced_str.append(str(not is_unvoiced).lower())

    content.append("\tvoiced: [" + ", ".join(voiced_str) + "];")

    content.append("};")
    content.append("")

    return "\n".join(content)


def main():
    ddi_path, ddb_path, dst_path, filename_style, gen_lab, gen_seg = parse_args()

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
        art_list: list[tuple[list, dict]] = []

        for idx, art_item in ddi_model.art_data.items():
            if "artu" in art_item:  # Triphoneme
                for idx, artu_item in art_item["artu"].items():
                    if "artp" in artu_item:
                        for idx, artp_item in artu_item["artp"].items():
                            phonemes = [art_item["phoneme"],
                                        artu_item["phoneme"]]
                            art_list.append((phonemes, artp_item))
                    if "artu" in artu_item:
                        for idx, artu2_item in artu_item["artu"].items():
                            if "artp" in artu2_item:
                                for idx, artp_item in artu2_item["artp"].items():
                                    phonemes = [
                                        art_item["phoneme"], artu_item["phoneme"], artu2_item["phoneme"]]
                                    art_list.append((phonemes, artp_item))

        for art_item in art_list:
            phonemes = art_item[0]
            art_item = art_item[1]

            _, t = art_item["snd"].split("=")
            snd_offset, _ = t.split("_")
            snd_offset = int(snd_offset, 16)

            pitch = art_item["pitch1"]

            output_path = os.path.join(dst_path, create_file_name(
                phonemes, filename_style, snd_offset, pitch, dst_path, "wav"))

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
                    lab_content = generate_lab(
                        phonemes, art_item["frame_align"], snd_frame_rate, snd_empt_bytes, snd_length)
                    lab_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, filename_style, snd_offset, pitch, dst_path, "lab"))
                    with open(lab_output_path, "w") as lab_f:
                        lab_f.write(lab_content)
                elif gen_seg:
                    unvoiced_consonant_list = ddi_model.phdc_data["phoneme"]["unvoiced"]
                    trans_content, seg_content, art_seg_content = generate_seg_files(
                        phonemes, art_item["frame_align"], snd_frame_rate, snd_empt_bytes,
                        snd_length, unvoiced_consonant_list
                    )

                    trans_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, filename_style, snd_offset, pitch, dst_path, "trans"))
                    seg_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, filename_style, snd_offset, pitch, dst_path, "seg"))
                    art_seg_output_path = os.path.join(dst_path, create_file_name(
                        phonemes, filename_style, snd_offset, pitch, dst_path, "as0"))

                    with open(trans_output_path, "w") as fp:
                        fp.write(trans_content)
                    with open(seg_output_path, "w") as fp:
                        fp.write(seg_content)
                    with open(art_seg_output_path, "w") as fp:
                        fp.write(art_seg_content)

        # Dump stationary
        for _, sta_info in ddi_model.sta_data.items():
            phoneme = sta_info["phoneme"]
            for sta_idx, sta_item in sta_info["stap"].items():
                _, snd_name = sta_item["snd"].split("=")
                snd_offset, snd_id = snd_name.split("_")

                snd_offset = int(snd_offset, 16)

                pitch = sta_item["pitch1"]

                output_path = os.path.join(dst_path, create_file_name(
                    [phoneme], filename_style, snd_offset, pitch, dst_path, "wav"))

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

                print("Dumped [%s] -> %s" % (phoneme, output_path))
                snd_pos_list.append(real_snd_offset)

        # Dump VQM
        if "vqm" in ddi_model.ddi_data_dict:
            for vqm_idx, vqm_info in ddi_model.vqm_data.items():
                _, snd_name = vqm_info["snd"].split("=")
                snd_offset, snd_id = snd_name.split("_")

                snd_offset = int(snd_offset, 16)
                snd_id = int(snd_id, 16)
                pitch = vqm_info["pitch1"]

                output_path = os.path.join(dst_path, create_file_name(
                    ["growl"], filename_style, snd_offset, pitch, dst_path, "wav"))
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
                            [], filename_style, snd_offset, 0, dst_path, "wav"))

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
