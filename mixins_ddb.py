#!/bin/env python3
# I thought what I'd do was, I'd pretend I was one of those deaf-mutes.
import argparse
import io
import re
import os
import os.path

from utils.ddi_utils import DDIModel

ddi_footer = b'\x05\x00\x00\x00' + "voice".encode()

def byte_replace(src_bytes: bytes, offset: int, override_len: int, replace_bytes: bytes):
    return src_bytes[:offset] + replace_bytes + src_bytes[offset + override_len:]

def parse_args(args=None):  # : list[str]
    # initialize parser
    parser = argparse.ArgumentParser()
    parser.add_argument('--src_path', required=True,
                        help='source ddi file path')
    parser.add_argument('--mixins_path', required=True,
                        help='the mixins ddi file path')
    parser.add_argument('--dst_path',
                        help='output folder, '
                        'default to be "./[singer name]/mixins"')
    parser.add_argument('--mixins_items',
                        help='mixins items, separated by ","'
                        'default to be "vqm", currently only support "vqm"')

    # parse args
    args = parser.parse_args(args)

    src_ddi_path: str = os.path.normpath(args.src_path)

    if not os.path.exists(src_ddi_path):
        raise Exception("ddi file not exists")

    src_path = os.path.dirname(src_ddi_path)
    src_singer_name = os.path.splitext(os.path.basename(src_ddi_path))[0]

    mixins_ddi_path: str = os.path.normpath(args.mixins_path)

    if not os.path.exists(mixins_ddi_path):
        raise Exception("mixins ddi file not exists")
    
    mixins_path = os.path.dirname(mixins_ddi_path)
    mixins_singer_name = os.path.splitext(os.path.basename(mixins_ddi_path))[0]

    dst_path: str = args.dst_path
    if dst_path is None:
        dst_path = os.path.join(src_path, "mixins")
    dst_path: str = os.path.normpath(dst_path)

    # make dirs
    if not os.path.exists(dst_path):
        os.makedirs(dst_path)

    return src_path, src_singer_name, mixins_path, mixins_singer_name, dst_path

def main():
    src_path, src_singer_name, mixins_path, mixins_singer_name, dst_path = parse_args()

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

    src_ddi_data = io.BytesIO(src_ddi_bytes)
    mixins_ddi_data = io.BytesIO(mixins_ddi_bytes)

    # Read DDI file
    print("Reading source DDI...")
    src_ddi_model = DDIModel(src_ddi_bytes)
    src_ddi_model.read()

    if "vqm" in src_ddi_model.ddi_data_dict:
        print("Source DDI already has vqm stream, continue will replace it and won't remove vqm stream from ddb file.")
        print("Continue? (Y/n)", end=" ")
        choice = input().strip().lower()
        if choice != "y" or choice != "":
            return

    print("Reading mixins DDI...")
    mixins_ddi_model = DDIModel(mixins_ddi_bytes)
    mixins_ddi_model.read()

    if "vqm" not in mixins_ddi_model.ddi_data_dict:
        raise Exception("Mixins DDI doesn't have vqm stream.")

    print("Creating DDB...")
    dst_ddb_file = dst_path + "/" + src_singer_name + ".ddb"
    with open(src_ddb_file, "rb") as in_f, open(dst_ddb_file, "wb") as out_f, open(mixins_ddb_file, "rb") as mixins_f:
        while in_f.readable():
            data = in_f.read(10240)
            if not data:
                break
            out_f.write(data)

        for vqm_info in mixins_ddi_model.ddi_data_dict["vqm"]:
            for epr_info in vqm_info["epr"]:
                ddi_epr_pos, epr_offset = epr_info.split("=")
                ddb_epr_offset = out_f.tell()

                ddi_epr_pos = int(ddi_epr_pos, 16)
                epr_offset = int(epr_offset, 16)

                mixins_f.seek(epr_offset)

                hed = mixins_f.read(4).decode()
                if hed != "FRM2":
                    raise Exception("Mixins DDB file is broken")
                
                frm_len = int.from_bytes(mixins_f.read(4), byteorder='little')

                mixins_f.seek(epr_offset)
                frm_bytes = mixins_f.read(frm_len)

                out_f.write(frm_bytes)

                # Change offset in ddi
                mixins_ddi_data.seek(ddi_epr_pos)
                mixins_ddi_data.write(ddb_epr_offset.to_bytes(8, byteorder="little"))

            ddi_snd_pos, snd_name = vqm_info["snd"].split("=")
            snd_offset, snd_id = snd_name.split("_")

            ddi_snd_pos = int(ddi_snd_pos, 16)
            snd_offset = int(snd_offset, 16)

            mixins_f.seek(snd_offset)
            hed = mixins_f.read(4).decode()
            if hed != "SND ":
                raise Exception("Mixins DDB file is broken")
            
            snd_len = int.from_bytes(mixins_f.read(4), byteorder='little')

            ddb_snd_offset = out_f.tell()

            mixins_f.seek(snd_offset)
            snd_bytes = mixins_f.read(snd_len)

            hed = snd_bytes[0:4].decode()
            if hed != "SND ":
                raise Exception("Mixins DDB file is broken")

            out_f.write(snd_bytes)

            # Change offset in ddi
            mixins_ddi_data.seek(ddi_snd_pos)
            mixins_ddi_data.write(ddb_snd_offset.to_bytes(8, byteorder="little"))

    print("Creating DDI...")
    dst_ddi_file = dst_path + "/" + src_singer_name + ".ddi"

    dst_mixins_bytes = mixins_ddi_data.getvalue()
    
    ddi_vqm_bytes = dst_mixins_bytes[mixins_ddi_model.offset_map["vqm"][0]:mixins_ddi_model.offset_map["vqm"][1]]

    if "vqm" in src_ddi_model.ddi_data_dict:
        ddi_replace_start = src_ddi_model.offset_map["vqm"][0]
        ddi_replace_end = src_ddi_model.offset_map["vqm"][1]
    else:
        ddi_replace_start = src_ddi_bytes.find(ddi_footer)
        ddi_replace_end = ddi_replace_start

        # Bump dbv_len
        dbv_len_post = src_ddi_model.offset_map["dbv"][0] + 0x18
        src_ddi_data.seek(dbv_len_post)
        src_ddi_dbv_len = int.from_bytes(src_ddi_data.read(4), byteorder='little')
        src_ddi_dbv_len += 1
        src_ddi_data.seek(dbv_len_post)
        src_ddi_data.write(src_ddi_dbv_len.to_bytes(4, byteorder='little'))

        src_ddi_bytes = src_ddi_data.getvalue()


    dst_ddi_bytes = byte_replace(src_ddi_bytes, ddi_replace_start, ddi_replace_end - ddi_replace_start, ddi_vqm_bytes)
    with open(dst_ddi_file, "wb") as f:
        f.write(dst_ddi_bytes)

    print("Finished...")


if __name__ == '__main__':
    main()
