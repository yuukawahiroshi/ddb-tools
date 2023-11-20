#!/bin/env python3
# I thought what I'd do was, I'd pretend I was one of those deaf-mutes.
from __future__ import annotations
from typing import TypedDict
import argparse
import io
import re
import os
import os.path
import struct

from utils.ddi_utils import DDIModel, str_to_bytes, str_to_data, stream_reverse_search

ddi_footer = b'\x05\x00\x00\x00' + "voice".encode()

class SmartFormatter(argparse.HelpFormatter):
    def _split_lines(self, text, width):
        if text.startswith('R|'):
            return text[2:].splitlines()  
        # this is the RawTextHelpFormatter._split_lines
        return argparse.HelpFormatter._split_lines(self, text, width)
    
class VQMMeta(TypedDict):
    idx: str
    epr: list[int]
    snd_id: int
    snd: int
    unknown1: str
    pitch1: float
    pitch2: float
    unknown2: float
    unknown3: float
    dynamics: float

def byte_replace(src_bytes: bytes, offset: int, override_len: int, replace_bytes: bytes):
    return src_bytes[:offset] + replace_bytes + src_bytes[offset + override_len:]

def parse_args(args=None):  # : list[str]
    # initialize parser
    parser = argparse.ArgumentParser(formatter_class=SmartFormatter)
    parser.add_argument('--src_path', required=True,
                        help='source ddi file path')
    parser.add_argument('--mixins_path',
                        help='the mixins ddi file path. default to be same as src_path')
    parser.add_argument('--dst_path',
                        help='output folder, '
                        'default to be "./[singer name]/mixins"')
    parser.add_argument('--mixins_item',
                        choices=['vqm', 'sta2vqm'],
                        default='vqm',
                        help='R|mixins item, '
                        'default to be "vqm"\n'
                        'select from: \n'
                        '    vqm: growl\n'
                        '    sta2vqm: convert stationary entry to growl\n')
    parser.add_argument('--sta2vqm_phoneme',
                        default="Grw",
                        help='phoneme for sta2vqm, will use this phoneme to generate growl, default to be "Grw"')


    # parse args
    args = parser.parse_args(args)

    src_ddi_path: str = os.path.normpath(args.src_path)

    if not os.path.exists(src_ddi_path):
        raise Exception("ddi file not exists")

    src_path = os.path.dirname(src_ddi_path)
    src_singer_name = os.path.splitext(os.path.basename(src_ddi_path))[0]

    mixins_ddi_path = args.mixins_path or src_ddi_path
    mixins_ddi_path: str = os.path.normpath(mixins_ddi_path)
    
    mixins_path = os.path.dirname(mixins_ddi_path)
    mixins_singer_name = os.path.splitext(os.path.basename(mixins_ddi_path))[0]

    dst_path: str = args.dst_path
    if dst_path is None:
        dst_path = os.path.join(src_path, "mixins")
    dst_path: str = os.path.normpath(dst_path)

    # make dirs
    if not os.path.exists(dst_path):
        os.makedirs(dst_path)

    mixins_item = args.mixins_item

    return src_path, src_singer_name, mixins_path, mixins_singer_name, dst_path, mixins_item, args

def _create_vqm_stream(vqm_meta_list: list[VQMMeta]):
    # Create VQM struct
    vqm_stream = io.BytesIO()
    vqm_stream.write(b'\xFF'*8)
    vqm_stream.write(b'VQM ')
    vqm_stream.write((0).to_bytes(4, byteorder='little'))
    vqm_stream.write((1).to_bytes(4, byteorder='little'))
    vqm_stream.write((0).to_bytes(4, byteorder='little'))
    vqm_stream.write((1).to_bytes(4, byteorder='little'))
    vqm_stream.write(b'\xFF'*8)

    vqm_stream.write(b'VQMu')
    vqm_stream.write((0).to_bytes(4, byteorder='little'))
    vqm_stream.write((1).to_bytes(4, byteorder='little'))
    vqm_stream.write((0).to_bytes(4, byteorder='little'))
    vqm_stream.write(len(vqm_meta_list).to_bytes(4, byteorder='little'))
    vqm_stream.write(len(vqm_meta_list).to_bytes(4, byteorder='little'))

    for vqm_meta in vqm_meta_list:
        vqm_stream.write(b'\xFF'*8)
        vqm_stream.write(b"VQMp")
        vqm_stream.write((0).to_bytes(4, byteorder='little'))
        vqm_stream.write((0).to_bytes(4, byteorder='little'))
        vqm_stream.write((1).to_bytes(4, byteorder='little'))
        vqm_stream.write(str_to_bytes(vqm_meta["unknown1"]))
        vqm_stream.write(struct.pack("<f", 224.0)) # Unknown
        vqm_stream.write(struct.pack("<f", vqm_meta["pitch2"]))
        vqm_stream.write(struct.pack("<f", vqm_meta["unknown2"]))
        vqm_stream.write(struct.pack("<f", vqm_meta["dynamics"]))
        vqm_stream.write(struct.pack("<f", vqm_meta["unknown3"]))
        vqm_stream.write((0).to_bytes(4, byteorder='little'))

        # EpR
        vqm_stream.write(b'\xFF'*4)
        vqm_stream.write(len(vqm_meta["epr"]).to_bytes(4, byteorder='little'))
        for epr_offset in vqm_meta["epr"]:
            vqm_stream.write(epr_offset.to_bytes(8, byteorder='little'))

        # SND
        vqm_stream.write(b'\x44\xAC\x00\x00')
        vqm_stream.write(b'\x01\x00')
        vqm_stream.write(vqm_meta["snd_id"].to_bytes(4, byteorder='little'))
        vqm_stream.write(vqm_meta["snd"].to_bytes(8, byteorder='little'))
        vqm_stream.write(b'\xFF'*0x10)

        vqm_stream.write(str_to_data(vqm_meta["idx"]))

    vqm_stream.write(str_to_data("GROWL"))
    vqm_stream.write(str_to_data("vqm"))

    return vqm_stream


def mixins_vqm(src_ddi_bytes: bytes, output_stream: io.BufferedWriter, mixins_ddi_model: DDIModel, mixins_ddb_stream: io.BufferedReader):
    mixins_ddi_stream = mixins_ddi_model.ddi_data

    if "vqm" not in mixins_ddi_model.ddi_data_dict:
        raise Exception("Mixins DDI doesn't have vqm stream.")

    print("Reading source DDI...")
    src_ddi_model = DDIModel(src_ddi_bytes)
    src_ddi_model.read()

    src_ddi_stream = src_ddi_model.ddi_data

    if "vqm" in src_ddi_model.ddi_data_dict:
        print("Source DDI already has vqm stream, continue will replace it and won't remove vqm stream from ddb file.")
        print("Continue? (Y/n)", end=" ")
        choice = input().strip().lower()
        if choice != "y" or choice != "":
            return
        
    vqm_meta_list: list[VQMMeta] = []
    for vqm_idx, vqm_info in mixins_ddi_model.vqm_data.items():
        epr_list = []
        for epr_info in vqm_info["epr"]:
            ddi_epr_pos, epr_offset = epr_info.split("=")
            ddb_epr_offset = output_stream.tell()

            ddi_epr_pos = int(ddi_epr_pos, 16)
            epr_offset = int(epr_offset, 16)

            mixins_ddb_stream.seek(epr_offset)

            hed = mixins_ddb_stream.read(4).decode()
            if hed != "FRM2":
                raise Exception("Mixins DDB file is broken")
            
            frm_len = int.from_bytes(mixins_ddb_stream.read(4), byteorder='little')

            mixins_ddb_stream.seek(epr_offset)
            frm_bytes = mixins_ddb_stream.read(frm_len)

            output_stream.write(frm_bytes)

            epr_list.append(ddb_epr_offset)

        ddi_snd_pos, snd_name = vqm_info["snd"].split("=")
        snd_offset, snd_id = snd_name.split("_")

        ddi_snd_pos = int(ddi_snd_pos, 16)
        snd_offset = int(snd_offset, 16)
        snd_id = int(snd_id, 16)

        mixins_ddb_stream.seek(snd_offset)
        hed = mixins_ddb_stream.read(4).decode()
        if hed != "SND ":
            raise Exception("Mixins DDB file is broken")
        
        snd_len = int.from_bytes(mixins_ddb_stream.read(4), byteorder='little')

        ddb_snd_offset = output_stream.tell()

        mixins_ddb_stream.seek(snd_offset)
        snd_bytes = mixins_ddb_stream.read(snd_len)

        hed = snd_bytes[0:4].decode()
        if hed != "SND ":
            raise Exception("Mixins DDB file is broken")

        output_stream.write(snd_bytes)

        vqm_meta_list.append({
            "idx": vqm_idx,
            "epr": epr_list,
            "snd_id": snd_id,
            "snd": ddb_snd_offset,
            "unknown1": vqm_info["unknown1"],
            "pitch1": vqm_info["pitch1"],
            "pitch2": vqm_info["pitch2"],
            "unknown2": vqm_info["unknown2"],
            "unknown3": vqm_info["unknown3"],
            "dynamics": vqm_info["dynamics"],
        })
            
    
    # Create new DDI
    vqm_stream = _create_vqm_stream(vqm_meta_list)
    ddi_vqm_bytes = vqm_stream.getvalue()

    if "vqm" in src_ddi_model.ddi_data_dict:
        ddi_vqm_pos = src_ddi_model.offset_map["vqm"][0]
        ddi_vqm_end_pos = src_ddi_model.offset_map["vqm"][1]
    else:
        ddi_vqm_pos = src_ddi_bytes.find(ddi_footer)
        ddi_vqm_end_pos = ddi_vqm_pos

        # Bump dbv_len
        dbv_len_post = src_ddi_model.offset_map["dbv"][0] + 0x18
        src_ddi_stream.seek(dbv_len_post)
        src_ddi_dbv_len = int.from_bytes(src_ddi_stream.read(4), byteorder='little')
        src_ddi_dbv_len += 1
        src_ddi_stream.seek(dbv_len_post)
        src_ddi_stream.write(src_ddi_dbv_len.to_bytes(4, byteorder='little'))

        src_ddi_bytes = src_ddi_stream.getvalue()

    dst_ddi_bytes = byte_replace(src_ddi_bytes, ddi_vqm_pos, ddi_vqm_end_pos - ddi_vqm_pos, ddi_vqm_bytes)

    return dst_ddi_bytes

    
def mixins_sta2vqm(src_ddi_bytes: bytes, output_stream: io.BufferedWriter, mixins_ddi_model: DDIModel, mixins_ddb_stream: io.BufferedReader, sta2vqm_phoneme: str):
    mixins_ddi_stream = mixins_ddi_model.ddi_data

    print("Reading source DDI...")
    src_ddi_model = DDIModel(src_ddi_bytes)
    src_ddi_model.read()

    src_ddi_stream = src_ddi_model.ddi_data

    if "vqm" in src_ddi_model.ddi_data_dict:
        print("Source DDI already has vqm stream, continue will replace it and won't remove vqm stream from ddb file.")
        print("Continue? (Y/n)", end=" ")
        choice = input().strip().lower()
        if choice != "y" or choice != "":
            return
        
    # Find stationary in mixins
    mixins_sta_items = None
    for _, sta_items in mixins_ddi_model.sta_data.items():
        if sta_items["phoneme"] == sta2vqm_phoneme:
            mixins_sta_items = sta_items
            break
    
    if mixins_sta_items is None:
        raise Exception("Mixins DDI doesn't have stationary entry for phoneme \"%s\"" % sta2vqm_phoneme)

    vqm_meta_list: list[VQMMeta] = []
    vqm_idx = 0
    for sta_idx, sta_item in mixins_sta_items["stap"].items():
        output_epr_list = []

        # EpR
        epr_list = sta_item["epr"]
        if len(epr_list) < 100:
            print(f"Warning: EpR count is less than 100, EpR count: {len(epr_list)}")
            continue

        epr_list = epr_list[0:100]
        for epr_info in epr_list:
            epr_offset = epr_info.split("=")
            ddb_epr_offset = output_stream.tell()

            epr_offset = int(epr_offset[1], 16)

            mixins_ddb_stream.seek(epr_offset)

            hed = mixins_ddb_stream.read(4)
            if hed != b"FRM2":
                raise Exception("Mixins DDB file is broken")
            
            frm_len = int.from_bytes(mixins_ddb_stream.read(4), byteorder='little')
            epr_cutoff = epr_offset + frm_len

            mixins_ddb_stream.seek(epr_offset)
            frm_bytes = mixins_ddb_stream.read(frm_len)
            output_stream.write(frm_bytes)

            output_epr_list.append(ddb_epr_offset)

        # SND
        ddi_snd_pos, snd_name = sta_item["snd"].split("=")
        snd_offset, snd_id = snd_name.split("_")

        ddi_snd_pos = int(ddi_snd_pos, 16)
        snd_offset = int(snd_offset, 16)
        snd_id = int(snd_id, 16)

        real_snd_offset = stream_reverse_search(mixins_ddb_stream, b"SND ", snd_offset)
        print(f"Delta SND offset: {snd_offset - real_snd_offset:0>8x}")

        mixins_ddb_stream.seek(real_snd_offset)
        hed = mixins_ddb_stream.read(4)
        if hed != b"SND ":
            raise Exception("Mixins DDB file is broken")
        
        snd_len = int.from_bytes(mixins_ddb_stream.read(4), byteorder='little')
        
        mixins_ddb_stream.seek(real_snd_offset)
        snd_bytes = mixins_ddb_stream.read(snd_len)

        ddb_snd_offset = output_stream.tell()
        output_stream.write(snd_bytes)

        vqm_meta_list.append({
            "idx": str(vqm_idx),
            "epr": output_epr_list,
            "snd_id": snd_id,
            "snd": ddb_snd_offset,
            "unknown1": '2c fb b7 5b 72 93 e2 3f 01 00',
            "pitch1": sta_item["pitch1"],
            "pitch2": sta_item["pitch2"],
            "unknown2": sta_item["unknown2"],
            "unknown3": sta_item["unknown3"],
            "dynamics": sta_item["dynamics"],
        })

        vqm_idx += 1

    # Create new DDI
    vqm_stream = _create_vqm_stream(vqm_meta_list)
    ddi_vqm_bytes = vqm_stream.getvalue()

    if "vqm" in src_ddi_model.ddi_data_dict:
        ddi_vqm_pos = src_ddi_model.offset_map["vqm"][0]
        ddi_vqm_end_pos = src_ddi_model.offset_map["vqm"][1]
    else:
        ddi_vqm_pos = src_ddi_bytes.find(ddi_footer)
        ddi_vqm_end_pos = ddi_vqm_pos

        # Bump dbv_len
        dbv_len_post = src_ddi_model.offset_map["dbv"][0] + 0x18
        src_ddi_stream.seek(dbv_len_post)
        src_ddi_dbv_len = int.from_bytes(src_ddi_stream.read(4), byteorder='little')
        src_ddi_dbv_len += 1
        src_ddi_stream.seek(dbv_len_post)
        src_ddi_stream.write(src_ddi_dbv_len.to_bytes(4, byteorder='little'))

        src_ddi_bytes = src_ddi_stream.getvalue()

    dst_ddi_bytes = byte_replace(src_ddi_bytes, ddi_vqm_pos, ddi_vqm_end_pos - ddi_vqm_pos, ddi_vqm_bytes)

    return dst_ddi_bytes

def main():
    src_path, src_singer_name, mixins_path, mixins_singer_name, dst_path, mixins_item, args = parse_args()

    src_ddb_file = src_path + "/" + src_singer_name + ".ddb"
    if not os.path.exists(src_ddb_file):
        raise Exception("Source ddb file not exists.")
    
    src_ddi_file = src_path + "/" + src_singer_name + ".ddi"
    if not os.path.exists(src_ddi_file):
        raise Exception("Source ddi file not exists.")
    
    mixins_ddb_file = mixins_path + "/" + mixins_singer_name + ".ddb"
    if not os.path.exists(mixins_ddb_file):
        raise Exception("Mixins ddb file not exists.")
    
    mixins_ddi_file = mixins_path + "/" + mixins_singer_name + ".ddi"
    if not os.path.exists(mixins_ddi_file):
        raise Exception("Mixins ddi file not exists.")

    with open(src_ddi_file, "rb") as f:
        src_ddi_bytes = f.read()
    with open(mixins_ddi_file, "rb") as f:
        mixins_ddi_bytes = f.read()

    src_ddi_stream = io.BytesIO(src_ddi_bytes)
    mixins_ddi_stream = io.BytesIO(mixins_ddi_bytes)

    print("Reading mixins DDI...")
    mixins_ddi_model = DDIModel(mixins_ddi_bytes)
    mixins_ddi_model.read()


    print("Creating DDB...")
    dst_ddb_file = dst_path + "/" + src_singer_name + ".ddb"
    dst_ddi_bytes = src_ddi_bytes
    with open(src_ddb_file, "rb") as src_ddb_stream, open(dst_ddb_file, "wb") as dst_ddb_stream, open(mixins_ddb_file, "rb") as mixins_ddb_stream:
        while src_ddb_stream.readable():
            data = src_ddb_stream.read(10240)
            if not data:
                break
            dst_ddb_stream.write(data)

        if mixins_item == "vqm":
            dst_ddi_bytes = mixins_vqm(dst_ddi_bytes, dst_ddb_stream, mixins_ddi_model, mixins_ddb_stream)
        elif mixins_item == "sta2vqm":
            dst_ddi_bytes = mixins_sta2vqm(dst_ddi_bytes, dst_ddb_stream, mixins_ddi_model, mixins_ddb_stream, args.sta2vqm_phoneme)

    print("Creating DDI...")
    dst_ddi_file = dst_path + "/" + src_singer_name + ".ddi"
    with open(dst_ddi_file, "wb") as f:
        f.write(dst_ddi_bytes)

    print("Finished...")


if __name__ == '__main__':
    main()
