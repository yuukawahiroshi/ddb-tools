#!/usr/bin/env python3

from __future__ import annotations
import io
import os
import struct
from typing import Optional

artp_type = dict[str, str | list[str]]
artu_type = dict[str, str | dict[int, artp_type]]
art_type = dict[str, str | dict[int, artu_type | dict]]

# class PhonemeModelInfo(TypedDict):
#     phoneme: str
#     ddi_epr_pos: int
#     epr: list[str]
#     ddi_snd_pos: int
#     snd_offset: int
#     snd_start: int


def bytes_to_str(data: bytes, add_spaces: bool = True) -> str:
    if add_spaces:
        return ' '.join([f'{piece:02x}' for piece in list(data)])
    else:
        return ''.join([f'{piece:02x}' for piece in list(data)])

def str_to_bytes(data: str) -> bytes:
    return bytes([int(piece, 16) for piece in data.split(' ')])

def read_str(data: io.BytesIO) -> str:
    str_size = int.from_bytes(data.read(4), byteorder='little')
    return data.read(str_size).decode()

def str_to_data(data: str) -> bytes:
    data = str(data)
    return len(data).to_bytes(4, byteorder='little') + data.encode()

def read_arr(data: io.BytesIO) -> bytes:
    assert data.read(4).decode() == 'ARR '
    int.from_bytes(data.read(4), byteorder='little')    # == 0   Exception: Tonio.ddi
    assert int.from_bytes(data.read(8), byteorder='little') == 1
    return data.read(4)

def reverse_search(data: bytes, search: bytes, offset: int, limit: int = -1) -> int:
    if limit == -1:
        limit = offset - len(search)
    offset -= len(search)
    for i in range(offset, 0, -1):
        if data[i:i+len(search)] == search:
            return i
        if offset - i > limit:
            break

    return -1

def stream_reverse_search(data: io.BufferedReader, search: bytes, offset: int, limit: int = -1) -> int:
    if limit == -1:
        limit = 1024 * 1024 * 10
    offset -= len(search)
    for i in range(offset, 0, -1):
        data.seek(i)
        if data.read(len(search)) == search:
            return i
        if offset - i > limit:
            break

    return -1

# ----------------------------------------- #

class DDIModel:
    def __init__(self, ddi_bytes: bytes) -> None:
        self.ddi_bytes = ddi_bytes
        self.ddi_data = None
        self.phdc_data = {}
        self.tdb_data = {}
        self.sta_data = {}
        self.art_data = {}
        self.vqm_data = {}
        self.offset_map = {}

    def read(self, temp_path: Optional[str] = None, cat_only: bool = False):
        if temp_path or cat_only:
            import yaml

        if cat_only:
            with open(os.path.join(temp_path, 'sta.yml'), mode='r',
                    encoding='utf-8') as sta_f:
                self.sta_data = yaml.load(sta_f)
            with open(os.path.join(temp_path, 'art.yml'), mode='r',
                    encoding='utf-8') as art_f:
                self.art_data = yaml.load(art_f)
            vqm_data = None
            if os.path.isfile(os.path.join(temp_path, 'vqm.yml')):
                with open(os.path.join(temp_path, 'vqm.yml'), mode='r',
                        encoding='utf-8') as vqm_f:
                    self.vqm_data = yaml.load(vqm_f)
        else:
            self.ddi_data = io.BytesIO(self.ddi_bytes)
            # DBSe
            # Tonio.ddi has no DBSe block
            
            # assert int.from_bytes(ddi_data.read(8), byteorder='little') == 0
            # assert ddi_data.read(4).decode() == 'DBSe'
            # assert int.from_bytes(ddi_data.read(4), byteorder='little') == 0
            # assert int.from_bytes(ddi_data.read(8), byteorder='little') == 1
            # assert int.from_bytes(ddi_data.read(4), byteorder='little') == 3

            # PHDC
            phdc_offset = self.ddi_bytes.find(b'PHDC')
            if phdc_offset >= 0:
                self.ddi_data.seek(phdc_offset)
                self.phdc_data = self.read_phdc()

                self.offset_map['phdc'] = [phdc_offset, self.ddi_data.tell()]

                if temp_path:
                    with open(os.path.join(temp_path, 'phdc.yml'), mode='w',
                            encoding='utf-8') as phdc_f:
                        phdc_str = yaml.dump(self.phdc_data, default_flow_style=False,
                                            sort_keys=False)
                        phdc_f.write(phdc_str)

            # TDB
            tdb_offset = self.ddi_bytes.find(b'\xFF'*8+b'TDB ')
            if tdb_offset >= 0:
                self.ddi_data.seek(tdb_offset)
                self.tdb_data = self.read_tdb()
                self.offset_map['tdb'] = [tdb_offset, self.ddi_data.tell()]

                if temp_path:
                    with open(os.path.join(temp_path, 'tdb.yml'), mode='w',
                            encoding='utf-8') as tdb_f:
                        tdb_str = yaml.dump(self.tdb_data, default_flow_style=False,
                                            sort_keys=False)
                        tdb_f.write(tdb_str)

            # DBV
            dbv_offset = self.ddi_bytes.find(b'\x00'*8+b'DBV ')
            self.ddi_data.seek(dbv_offset)
            self.read_dbv()
            self.offset_map['dbv'] = [dbv_offset, self.ddi_data.tell()]

            # STA
            sta_offset = self.ddi_bytes.find(b'\x00'*8+b'STA ')
            sta_offset = reverse_search(self.ddi_bytes, b'ARR ', sta_offset) - 8
            self.ddi_data.seek(sta_offset)
            self.sta_data = self.read_sta()
            self.offset_map['sta'] = [sta_offset, self.ddi_data.tell()]

            if temp_path:
                with open(os.path.join(temp_path, 'sta.yml'), mode='w',
                        encoding='utf-8') as sta_f:
                    sta_str = yaml.dump(self.sta_data, default_flow_style=False,
                                        sort_keys=False)
                    sta_f.write(sta_str)

            # ART
            art_offset = self.ddi_bytes.find(b'\x00'*8+b'ART ')
            art_offset = reverse_search(self.ddi_bytes, b'ARR ', art_offset) - 8
            self.ddi_data.seek(art_offset)
            self.art_data = self.read_art()
            self.offset_map['art'] = [art_offset, self.ddi_data.tell()]

            if temp_path:
                with open(os.path.join(temp_path, 'art.yml'), mode='w',
                        encoding='utf-8') as art_f:
                    art_str = yaml.dump(self.art_data, default_flow_style=False,
                                        sort_keys=False)
                    art_f.write(art_str)

            # VQM
            vqm_offset = self.ddi_bytes.find(b'\xFF'*8+b'VQM ')
            self.vqm_data = None
            if vqm_offset != -1:
                self.ddi_data.seek(vqm_offset)
                self.vqm_data = self.read_vqm()
                self.offset_map['vqm'] = [vqm_offset, self.ddi_data.tell()]

                if temp_path:
                    with open(os.path.join(temp_path, 'vqm.yml'), mode='w',
                            encoding='utf-8') as vqm_f:
                        vqm_str = yaml.dump(self.vqm_data, default_flow_style=False,
                                            sort_keys=False)
                        vqm_f.write(vqm_str)
        
        
        # DDI convert
        self.ddi_data_dict: dict[str, dict[str, list[artp_type]]] = {
            'sta': {},
            'art': {},
        }

        if self.vqm_data is not None:
            self.ddi_data_dict = {
                'vqm': {},
                'sta': {},
                'art': {},
            }
            vqm_dict = []
            for idx, vqmp in self.vqm_data.items():
                vqm_dict.append({'snd': vqmp['snd'], 'epr': vqmp['epr'], 'pitch': vqmp['pitch1']})
            self.ddi_data_dict['vqm'] = vqm_dict

        sta_dict: dict[str, list[artp_type]] = {}
        for stau in self.sta_data.values():
            stau_dict: list[artp_type] = []
            for idx, stap in stau['stap'].items():
                stau_dict.append({'snd': stap['snd'], 'epr': stap['epr'], 'pitch': stap['pitch1']})
            sta_dict[stau['phoneme']] = stau_dict
        self.ddi_data_dict['sta'] = {key: sta_dict[key]
                                for key in sorted(sta_dict.keys())}

        art_dict: dict[str, list[artp_type]] = {}
        for art in self.art_data.values():
            if 'artu' in art.keys():
                for artu in art['artu'].values():
                    key = art['phoneme']+' '+artu['phoneme']
                    art_dict[key] = []
                    for artp in artu['artp'].values():
                        art_dict[key].append({'snd': artp['snd'],
                                            'snd_start': artp['snd_start'],
                                            'epr': artp['epr'],
                                            'pitch': artp['pitch1']})
            if 'art' in art.keys():
                for sub_art in art['art'].values():
                    sub_art: art_type
                    if 'artu' in sub_art.keys():
                        for artu in sub_art['artu'].values():
                            key = art['phoneme']+' '+sub_art['phoneme']+' '+artu['phoneme']
                            art_dict[key] = []
                            for artp in artu['artp'].values():
                                art_dict[key].append({'snd': artp['snd'],
                                                    'snd_start': artp['snd_start'],
                                                    'epr': artp['epr'],
                                                    'pitch': artp['pitch1']})
        self.ddi_data_dict['art'] = {key: art_dict[key]
                                for key in sorted(art_dict.keys())}


    def save(self, dst_path: Optional[str] = None):
        import yaml

        with open(os.path.join(dst_path, 'ddi.yml'), mode='w', encoding='utf-8') as ddi_f:
            ddi_str = yaml.dump(self.ddi_data_dict, default_flow_style=False,
                                sort_keys=False)
            ddi_f.write(ddi_str)


    def read_phdc(self):
        phdc_data: dict[str, dict[int, list[str]]
                        | dict[str, dict[int, str]]
                        | dict[str, list[str]]
                        | str]
        phdc_data = {}
        # PHDC
        phoneme_data: dict[int, list[str]] = {0: [], 1: []}
        assert self.ddi_data.read(4).decode() == 'PHDC'
        phdc_size = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 4
        phoneme_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        for i in range(phoneme_num):
            bytes_str = self.ddi_data.read(0x1F)
            assert bytes_str[-1] in [0, 1]
            real_data = bytes_str[:-1].decode().strip('\x00')
            phoneme_data[bytes_str[-1]].append(real_data)
        phdc_data['phoneme'] = phoneme_data

        # PHG2
        phg2_data: dict[str, dict[int, str]] = {}
        assert self.ddi_data.read(4).decode() == 'PHG2'
        phg2_size = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        phg2_category_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        for i in range(phg2_category_num):
            phg2_key = read_str(self.ddi_data)
            phg2_data[phg2_key] = {}
            temp_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            for j in range(temp_num):
                idx = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                phg2_data[phg2_key][idx] = read_str(self.ddi_data)
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
        phdc_data['phg2'] = phg2_data

        # category
        category_data: dict[str, list[str]] = {}
        category_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        category_size = phdc_size-phg2_size-0x10-0x1F*phoneme_num-4
        category_bytes = self.ddi_data.read(category_size)
        offset = 0
        for i in range(category_num):
            key = category_bytes[offset:offset+0x20].decode().strip('\x00')
            assert int.from_bytes(category_bytes[offset+0x20:offset+0x24],
                                byteorder='little') == 4
            category_data[key] = []
            offset += 0x24
            while(offset < len(category_bytes) and category_bytes[offset] == 0):
                if category_bytes[offset+7] == 0x40:
                    value = category_bytes[offset:offset + 7]
                    start_idx = 0
                    for i in range(7):
                        if value[i] != 0:
                            start_idx = i
                            break
                    # TODO: Need to check carefully. "b'XXX'" and we only take XXX
                    value = bytes_to_str(value[start_idx:])
                    category_data[key].append(value)
                else:
                    assert int.from_bytes(category_bytes[offset:offset + 8],
                                        byteorder='little') == 0
                    category_data[key].append('')
                offset += 8
        assert offset == len(category_bytes)
        phdc_data['category'] = category_data

        # hash string
        # phdc_data['hash'] = self.ddi_data.read(0x20).decode()
        # assert int.from_bytes(self.ddi_data.read(0xE0), byteorder='little') == 0
        # assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
        # assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 2

        return phdc_data


    def read_tdb(self) -> dict[int, str]:
        tdb_data: dict[int, str] = {}
        assert self.ddi_data.read(8) == b'\xFF'*8
        assert self.ddi_data.read(4).decode() == 'TDB '
        int.from_bytes(self.ddi_data.read(4), byteorder='little')    # == 0 Exception: Tonio.ddi (B9 13 10 00)
        assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 1
        tmm_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        str_list = ['pitch', 'dynamics', 'opening']
        for i in range(tmm_num):
            assert self.ddi_data.read(8) == b'\xFF'*8
            assert self.ddi_data.read(4).decode() == 'TMM '
            int.from_bytes(self.ddi_data.read(4), byteorder='little')    # == 0 Exception: Tonio.ddi
            assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 1
            idx = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            # print(i, idx)
            str_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            assert str_num == 3
            for j in range(str_num):
                assert self.ddi_data.read(8) == b'\xFF'*8
                assert int.from_bytes(read_arr(self.ddi_data), byteorder='little') == 0
                assert read_str(self.ddi_data) == str_list[j]
            phoneme = read_str(self.ddi_data)
            tdb_data[idx] = phoneme
        assert read_str(self.ddi_data) == 'timbre'
        return tdb_data


    def read_dbv(self) -> None:
        assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 0
        assert self.ddi_data.read(4).decode() == 'DBV '
        int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
        assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 1
        int.from_bytes(self.ddi_data.read(4), byteorder='little')    # 4 for AVANNA, 5 for others?


    def read_sta(self) -> dict[int, artu_type]:
        sta_data: dict[int, artu_type] = {}
        assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 0
        assert int.from_bytes(read_arr(self.ddi_data), byteorder='little') == 1
        assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 0

        assert self.ddi_data.read(4).decode() == 'STA '
        int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
        assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 1
        stau_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        for i in range(stau_num):
            stau_data: artu_type = {'phoneme': '', 'stap': {}}
            assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 0
            assert self.ddi_data.read(4).decode() == 'STAu'
            int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
            stau_idx = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            assert self.ddi_data.read(8) == b'\xFF'*8
            stap_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            for j in range(stap_num):
                stap_data: artp_type = {'snd': '', 'snd_length': '', 'epr': []}
                _pos = self.ddi_data.tell()
                assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 0
                assert self.ddi_data.read(4).decode() == 'STAp'
                int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
                stap_data['unknown1'] = bytes_to_str(self.ddi_data.read(0x0a))
                stap_data['pitch1'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                stap_data['pitch2'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                stap_data['unknown2'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                stap_data['dynamics'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                stap_data['unknown3'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 2
                assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 0x3D
                assert self.ddi_data.read(4).decode() == 'EMPT'
                int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
                assert read_str(self.ddi_data) == 'SND'
                stap_data['snd_length'] = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
                assert self.ddi_data.read(4).decode() == 'EMPT'
                int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
                assert read_str(self.ddi_data) == 'EpR'
                self.ddi_data.read(4)  # == b'\xFF'*4  Exception: Tonio.ddi (epr_num)
                epr_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                epr_list: list[str] = []
                for k in range(epr_num):
                    epr_offset_pos = self.ddi_data.tell()
                    epr_offset = int.from_bytes(self.ddi_data.read(8),
                                                byteorder='little')
                    epr_list.append(f'{epr_offset_pos:0>8x}={epr_offset:0>8x}')
                stap_data['epr'] = epr_list
                stap_data['fs'] = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                assert self.ddi_data.read(2) == b'\x01\x00'
                snd_identifier = int.from_bytes(self.ddi_data.read(4),
                                                byteorder='little')
                # TODO: why this number?
                snd_offset_pos = self.ddi_data.tell()
                snd_offset = int.from_bytes(self.ddi_data.read(8), byteorder='little')
                stap_data['snd'] = f'{snd_offset_pos:0>8x}={snd_offset:016x}_{snd_identifier:08x}'

                _pos = self.ddi_data.tell()
                stap_data['unknown4'] = bytes_to_str(self.ddi_data.read(0x10))
                stap_idx = read_str(self.ddi_data)
                assert stap_idx not in stau_data['stap'].keys()
                stau_data['stap'][stap_idx] = stap_data
            stau_data['stap'] = {k: stau_data['stap'][k]
                                for k in sorted(stau_data['stap'].keys())}
            stau_data['phoneme'] = read_str(self.ddi_data)
            sta_data[stau_idx] = stau_data
        sta_data = {k: sta_data[k] for k in sorted(sta_data.keys())}
        assert read_str(self.ddi_data) == 'normal'
        assert read_str(self.ddi_data) == 'stationary'
        return sta_data


    def read_art(self) -> dict[int, art_type]:
        total_art_data: dict[int, art_type] = {}
        int.from_bytes(self.ddi_data.read(8), byteorder='little')  # == 0 Exception: Tonio.ddi
        assert int.from_bytes(read_arr(self.ddi_data), byteorder='little') != 0
        while(True):
            start = self.ddi_data.read(8)
            if not (start in [b'\x00'*8, b'\xFF'*8]):
                offset = self.ddi_data.tell()-8
                self.ddi_data.seek(offset)
                assert read_str(self.ddi_data) == 'articulation'
                break
            assert self.ddi_data.read(4).decode() == 'ART '
            art_idx, art_data = self.read_art_block()
            total_art_data[art_idx] = art_data
        total_art_data = {key: total_art_data[key]
                        for key in sorted(total_art_data.keys())}
        return total_art_data


    def read_art_block(self) -> tuple[int, art_type]:
        art_data: art_type = {'phoneme': '', 'artu': {}, 'art': {}}
        int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
        art_idx = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        artu_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        i = -1
        for i in range(artu_num):
            artu_data: artu_type = {'phoneme': '', 'artp': {}}
            assert int.from_bytes(self.ddi_data.read(8), byteorder='little') == 0
            block_type = self.ddi_data.read(4).decode()
            if block_type == 'ART ':
                sub_art_idx, sub_art_data = self.read_art_block()
                art_data['art'][sub_art_idx] = sub_art_data
                continue
            else:
                assert block_type == 'ARTu'
            int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
            artu_idx = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            # TODO: why to be 1?
            assert int.from_bytes(self.ddi_data.read(8),
                                byteorder='little') in [0, 1]
            self.ddi_data.read(4)
            assert self.ddi_data.read(4) == b'\xFF'*4
            artp_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            for j in range(artp_num):
                artp_data: artp_type = {'snd': '', 'snd_unknown': '', 'epr': []}
                dev_artp_offset = int.from_bytes(self.ddi_data.read(8), byteorder='little')
                artp_data['dev_artp'] = f'{dev_artp_offset:0>8x}'
                assert self.ddi_data.read(4).decode() == 'ARTp'
                int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
                artp_data['unknown1'] = bytes_to_str(self.ddi_data.read(0x0a))
                artp_data['pitch1'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                artp_data['pitch2'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                artp_data['unknown2'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                artp_data['dynamics'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                artp_data['unknown3'] = struct.unpack('<f', self.ddi_data.read(4))[0]
                # print(f'art {i:4d} {j:4d} {unknown}')
                # if env['unknown'] is None:
                #     env['unknown'] = unknown
                # else:
                #     assert env['unknown'] == unknown
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 2
                # TODO: This doesn't seem to be an index actually
                artp_idx = int.from_bytes(self.ddi_data.read(8), byteorder='little')
                assert self.ddi_data.read(4).decode() == 'EMPT'
                int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
                assert read_str(self.ddi_data) == 'SND'
                unknown_snd = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                artp_data['snd_unknown'] = f'{unknown_snd:08x}'
                assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
                assert self.ddi_data.read(4).decode() == 'EMPT'
                int.from_bytes(self.ddi_data.read(4), byteorder='little')  # == 0 Exception: Tonio.ddi
                assert read_str(self.ddi_data) == 'EpR'
                loc = self.ddi_data.tell()
                try:
                    epr_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                    epr_list: list[str] = []
                    for k in range(epr_num):
                        epr_offset_pos = self.ddi_data.tell()
                        epr_offset = int.from_bytes(self.ddi_data.read(8),
                                                    byteorder='little')
                        epr_list.append(f'{epr_offset_pos:0>8x}={epr_offset:0>8x}')
                    artp_data['epr'] = epr_list
                    artp_data['fs'] = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                    assert self.ddi_data.read(2) == b'\x01\x00'
                except AssertionError:
                    self.ddi_data.seek(loc)
                    self.ddi_data.read(4)  # == b'\xFF'*4  Exception: Tonio.ddi (epr_num)
                    epr_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                    epr_list: list[str] = []
                    for k in range(epr_num):
                        epr_offset_pos = self.ddi_data.tell()
                        epr_offset = int.from_bytes(self.ddi_data.read(8),
                                                    byteorder='little')
                        epr_list.append(f'{epr_offset_pos:0>8x}={epr_offset:0>8x}')
                    artp_data['epr'] = epr_list
                    artp_data['fs'] = int.from_bytes(self.ddi_data.read(4), byteorder='little')
                    assert self.ddi_data.read(2) == b'\x01\x00'
                    
                snd_identifier = int.from_bytes(self.ddi_data.read(4),
                                                byteorder='little')
                # TODO: why this number?
                snd_offset_pos = self.ddi_data.tell()
                snd_offset = int.from_bytes(self.ddi_data.read(8), byteorder='little')
                artp_data['snd'] = f'{snd_offset_pos:08x}={snd_offset-0x12:016x}_{snd_identifier:08x}'

                snd_offset2_pos = self.ddi_data.tell()
                snd_offset2 = int.from_bytes(self.ddi_data.read(8), byteorder='little')  # == snd_offset+0x800  Exception: Tonio.ddi (0)
                artp_data['snd_start'] = f'{snd_offset2_pos:08x}={snd_offset2-0x12:016x}_{snd_identifier:08x}'

                ddi_bytes: bytes = self.ddi_bytes[self.ddi_data.tell():self.ddi_data.tell() + 1024]
                align_length = ddi_bytes.find(b'default')-4
                align_bytes = self.ddi_data.read(align_length)
                frame_align = []
                if align_length > 4:
                    align_group_num = int.from_bytes(align_bytes[0:4], byteorder='little')
                    # In V3 format, each group has int32 * 4 bytes
                    align_bytes = align_bytes[4:]
                    align_io = io.BytesIO(align_bytes)
                    for _ in range(0, align_group_num):
                        frame_align_group = {
                            "start": int.from_bytes(align_io.read(4), byteorder='little'),
                            "end": int.from_bytes(align_io.read(4), byteorder='little'),
                            "start2": int.from_bytes(align_io.read(4), byteorder='little'),
                            "end2": int.from_bytes(align_io.read(4), byteorder='little'),
                        }
                        frame_align.append(frame_align_group)
                else: # V2 format
                    frame_align_group = []
                    for i in range(0, len(align_bytes), 4):
                        frame_align_group.append(int.from_bytes(align_bytes[i:i+4], byteorder='little'))
                    frame_align.append(frame_align_group)
                artp_data['frame_align'] = frame_align
                
                assert read_str(self.ddi_data) == 'default'

                assert artp_idx not in artu_data['artp'].keys()
                artu_data['artp'][artp_idx] = artp_data
            artu_data['artp'] = {k: artu_data['artp'][k]
                                for k in sorted(artu_data['artp'].keys())}
            artu_data['phoneme'] = read_str(self.ddi_data)
            art_data['artu'][artu_idx] = artu_data
        art_data['artu'] = {k: art_data['artu'][k]
                            for k in sorted(art_data['artu'].keys())}
        art_data['art'] = {k: art_data['art'][k]
                        for k in sorted(art_data['art'].keys())}
        art_data['phoneme'] = read_str(self.ddi_data)
        if len(art_data['art'].keys()) == 0:
            del art_data['art']
        if len(art_data['artu'].keys()) == 0:
            del art_data['artu']
        return art_idx, art_data


    def read_vqm(self) -> dict[int, artp_type]:
        vqm_data: dict[int, artp_type] = {}

        assert self.ddi_data.read(8) == b'\xFF'*8
        assert self.ddi_data.read(4).decode() == 'VQM '
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
        assert self.ddi_data.read(8) == b'\xFF'*8

        assert self.ddi_data.read(4).decode() == 'VQMu'
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0

        vqmp_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
        assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == vqmp_num
        for i in range(vqmp_num):
            vqmp_data = {'snd': '', 'epr': []}
            assert self.ddi_data.read(8) == b'\xFF'*8
            assert self.ddi_data.read(4).decode() == 'VQMp'
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 1
            vqmp_data['unknown1'] = bytes_to_str(self.ddi_data.read(0x0a))
            vqmp_data['pitch1'] = struct.unpack('<f', self.ddi_data.read(4))[0]
            vqmp_data['pitch2'] = struct.unpack('<f', self.ddi_data.read(4))[0]
            vqmp_data['unknown2'] = struct.unpack('<f', self.ddi_data.read(4))[0]
            vqmp_data['dynamics'] = struct.unpack('<f', self.ddi_data.read(4))[0]
            # TODO: that may not be same as env['unknown']
            vqmp_data['unknown3'] = struct.unpack('<f', self.ddi_data.read(4))[0]
            assert int.from_bytes(self.ddi_data.read(4), byteorder='little') == 0
            assert self.ddi_data.read(4) == b'\xFF'*4
            epr_num = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            epr_list: list[str] = []
            for k in range(epr_num):
                ddi_epr_offset = self.ddi_data.tell()
                epr_offset = int.from_bytes(self.ddi_data.read(8), byteorder='little')
                epr_list.append(f'{ddi_epr_offset:0>8x}={epr_offset:0>8x}')
            vqmp_data['epr'] = epr_list
            vqmp_data['fs'] = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            assert self.ddi_data.read(2) == b'\x01\x00'
            snd_identifier = int.from_bytes(self.ddi_data.read(4), byteorder='little')
            ddi_snd_offset = self.ddi_data.tell()
            snd_offset = int.from_bytes(self.ddi_data.read(8), byteorder='little')
            vqmp_data['snd'] = f'{ddi_snd_offset:0>8x}={snd_offset:016x}_{snd_identifier:08x}'
            assert self.ddi_data.read(0x10) == b'\xFF'*0x10
            vqmp_idx = int(read_str(self.ddi_data))
            vqm_data[vqmp_idx] = vqmp_data
        assert read_str(self.ddi_data) == 'GROWL'
        assert read_str(self.ddi_data) == 'vqm'
        return vqm_data
