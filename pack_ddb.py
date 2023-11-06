#!/bin/env python3
# I thought what I'd do was, I'd pretend I was one of those deaf-mutes.
import argparse
import io
import re
import os
import os.path

from utils.ddi_utils import DDIModel

def escape_filename(filename: str):
    escaped = ""
    for char in filename:
        if char >= 'a' and char <= 'z':
            escaped += char
        else:
            escaped += "%" + str(ord(char)) + "%"

    return escaped

def parse_args(args=None):  # : list[str]
    # initialize parser
    parser = argparse.ArgumentParser()
    parser.add_argument('--src_path', required=True,
                        help='singer tree file path')
    parser.add_argument('--dst_path',
                        help='destination path, '
                        'default to be "./[singer name]"')

    # parse args
    args = parser.parse_args(args)
    src_path: str = os.path.normpath(args.src_path)

    if not os.path.exists(src_path):
        raise Exception("singer tree file not exists")

    singer_path = re.sub(r"\.tree$", "", src_path)
    singer_name = os.path.basename(singer_path)

    dst_path: str = args.dst_path
    if dst_path is None:
        src_dir, src_filename = os.path.split(src_path)
        src_name, src_ext = os.path.splitext(src_filename)
        dst_filename = singer_name
        dst_path = os.path.join(src_dir, src_name, dst_filename)
    dst_path: str = os.path.normpath(dst_path)

    # make dirs
    if not os.path.exists(dst_path):
        os.makedirs(dst_path)

    return singer_path, singer_name, dst_path

def main():
    singer_path, singer_name, dst_path = parse_args()

    singer_tree_path = singer_path + ".tree"
    if not os.path.exists(singer_tree_path):
        raise Exception("Singer tree file not exists.")

    with open(singer_tree_path, "rb") as f:
        ddi_bytes = f.read()

    ddi_data = io.BytesIO(ddi_bytes)

    ddi_path = dst_path + "/" + singer_name + ".ddi"
    ddb_path = dst_path + "/" + singer_name + ".ddb"

    if os.path.exists(ddi_path):
        os.remove(ddi_path)

    if os.path.exists(ddb_path):
        os.remove(ddb_path)

    # Read DDI file
    print("Reading DDI...")

    ddi_model = DDIModel(ddi_bytes)
    ddi_model.read()

    print("Creating DDB...")
    
    with open(ddb_path, "wb") as ddb_f:
        for cvvc, art_items in ddi_model.ddi_data_dict["art"].items():
            phonemes = cvvc.split(' ')
            if len(phonemes) == 3: # vcv
                art_file = singer_path + "/voice/articulation/" + escape_filename(phonemes[0]) + "/" + escape_filename(phonemes[1]) + "/" + escape_filename(phonemes[2])
            elif len(phonemes) == 2: #cvvc
                art_file = singer_path + "/voice/articulation/" + escape_filename(phonemes[0]) + "/" + escape_filename(phonemes[1])

            print("Adding art file: %s" % art_file)
            if not os.path.exists(art_file):
                raise Exception("Articulation file \"%s\" not found" % art_file)
            
            with open(art_file, "rb") as art_f:
                art_bytes = art_f.read()

            with io.BytesIO(art_bytes) as art_data:
                for i in range(0, len(art_items)):
                    art_item = art_items[i]

                    # Add Articulation EpR to ddb
                    for epr_info in art_item["epr"]:
                        ddi_epr_pos, epr_offset = epr_info.split("=")
                        ddb_epr_offset = ddb_f.tell()

                        ddi_epr_pos = int(ddi_epr_pos, 16)
                        epr_offset = int(epr_offset, 16)

                        art_data.seek(epr_offset)

                        hed = art_data.read(4).decode()
                        if hed != "FRM2":
                            raise Exception("Articulation file \"%s\" is broken" % art_file)
                        
                        frm_len = int.from_bytes(art_data.read(4), byteorder='little')
                        epr_cutoff = epr_offset + frm_len

                        ddb_f.write(art_bytes[epr_offset:epr_cutoff])

                        # Change offset in ddi
                        ddi_data.seek(ddi_epr_pos)
                        ddi_data.write(ddb_epr_offset.to_bytes(8, byteorder="little"))

                    ddi_snd_pos, t = art_item["snd"].split("=")
                    snd_offset, _ = t.split("_")

                    ddi_snd_pos2, t = art_item["snd_cutoff"].split("=")
                    snd_offset2, _ = t.split("_")

                    ddi_snd_pos = int(ddi_snd_pos, 16)
                    snd_offset = int(snd_offset, 16)

                    ddi_snd_pos2 = int(ddi_snd_pos2, 16)
                    snd_offset2 = int(snd_offset2, 16)

                    offset2_delta = snd_offset2 - snd_offset

                    art_data.seek(snd_offset)
                    hed = art_data.read(4).decode()
                    if hed != "SND ":
                        raise Exception("Articulation file \"%s\" is broken" % art_file)
                    
                    snd_len = int.from_bytes(art_data.read(4), byteorder='little')
                    snd_cutoff = snd_offset + snd_len

                    ddb_snd_offset = ddb_f.tell() + 0x12

                    snd_bytes = art_bytes[snd_offset:snd_cutoff]

                    hed = snd_bytes[0:4].decode()
                    if hed != "SND ":
                        raise Exception("Articulation file \"%s\" is broken" % art_file)

                    ddb_f.write(snd_bytes)

                    # Change offset in ddi
                    ddi_data.seek(ddi_snd_pos)
                    ddi_data.write(ddb_snd_offset.to_bytes(8, byteorder="little"))
                    ddi_data.write((ddb_snd_offset + offset2_delta).to_bytes(8, byteorder="little"))

        for phoneme, sta_items in ddi_model.ddi_data_dict["sta"].items():
            for i in range(0, len(sta_items)):
                sta_item: dict[str, dict] = sta_items[i]

                sta_file = singer_path + "/voice/stationary/normal/" + escape_filename(phoneme) + "/" + escape_filename(str(i))
                print("Adding sta file: %s" % sta_file)
                if not os.path.exists(sta_file):
                    raise Exception("Stationary file \"%s\" not found" % sta_file)

                with open(sta_file, "rb") as sta_f:
                    sta_bytes = sta_f.read()

                with io.BytesIO(sta_bytes) as sta_data:
                    # Add Stationary EpR to ddb
                    for epr_info in sta_item["epr"]:
                        ddi_epr_pos, epr_offset = epr_info.split("=")
                        ddb_epr_offset = ddb_f.tell()

                        ddi_epr_pos = int(ddi_epr_pos, 16)
                        epr_offset = int(epr_offset, 16)

                        sta_data.seek(epr_offset)

                        hed = sta_data.read(4).decode()
                        if hed != "FRM2":
                            raise Exception("Stationary file \"%s\" is broken" % sta_file)
                        
                        frm_len = int.from_bytes(sta_data.read(4), byteorder='little')
                        epr_cutoff = epr_offset + frm_len

                        ddb_f.write(sta_bytes[epr_offset:epr_cutoff])

                        # Change offset in ddi
                        ddi_data.seek(ddi_epr_pos)
                        ddi_data.write(ddb_epr_offset.to_bytes(8, byteorder="little"))
                    
                    ddi_snd_pos, snd_name = sta_item["snd"].split("=")
                    snd_offset, snd_id = snd_name.split("_")

                    ddi_snd_pos = int(ddi_snd_pos, 16)
                    snd_offset = int(snd_offset, 16)

                    real_snd_offset = 0x3d
                    sta_data.seek(real_snd_offset)
                    hed = sta_data.read(4).decode()
                    if hed != "SND ":
                        raise Exception("Stationary file \"%s\" is broken" % sta_file)
                    
                    snd_len = int.from_bytes(sta_data.read(4), byteorder='little')
                    snd_cutoff = real_snd_offset + snd_len

                    delta_snd_offset = snd_offset - real_snd_offset
                    ddb_snd_offset = ddb_f.tell() + delta_snd_offset

                    snd_bytes = sta_bytes[real_snd_offset:snd_cutoff]

                    ddb_f.write(snd_bytes)

                    # Change offset in ddi
                    ddi_data.seek(ddi_snd_pos)
                    ddi_data.write(ddb_snd_offset.to_bytes(8, byteorder="little"))

    # Write DDI file
    print("Writing DDI...")
    with open(ddi_path, "wb") as f:
        f.write(ddi_data.getbuffer())

    print("Finished...")


if __name__ == '__main__':
    main()
