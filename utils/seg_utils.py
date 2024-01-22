from __future__ import annotations
import math
from typing import TypedDict


class ArticulationSegmentInfo(TypedDict):
    phonemes: list[str, str]
    boundaries: list[list[str, float, float]]

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
    phoneme_list: list[list], wav_length: float, is_sta: bool = False
) -> str:
    sil_phoneme = "unknown" if is_sta else "Sil"
    is_sta_int = 1 if is_sta else 0
    n_phonemes = len(phoneme_list) + 2  # Add 2 Sil

    content = [
        "nPhonemes %d" % n_phonemes,  # Add 2 Sil
        "articulationsAreStationaries = %d" % is_sta_int,
        "phoneme		BeginTime		EndTime",
        "===================================================",
    ]

    content.append("%s\t\t%.6f\t\t%.6f" % (sil_phoneme, 0, phoneme_list[0][1]))

    begin_time: float = 0
    end_time: float = 0
    for i in range(0, len(phoneme_list)):
        phoneme_info = phoneme_list[i]
        phoneme_name = phoneme_info[0]
        begin_time = phoneme_info[1]
        end_time = phoneme_info[2]

        content.append("%s\t\t%.6f\t\t%.6f" %
                       (phoneme_name, begin_time, end_time))

    content.append("%s\t\t%.6f\t\t%.6f" % (sil_phoneme, end_time, wav_length))

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