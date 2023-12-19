# ddb-tools
A modified version of ddb-extraction and adds functionality for: packaging ddi/ddb, mixins ddb

# ddb-extraction
![python>=3.10](https://img.shields.io/badge/python->=3.10-informational.svg)

> OneNote Link about ddi/ddb file strcutures:  
> https://1drv.ms/u/s!AgxVwvz3Kj1Ek49YzGjngt49krIZvQ

Extract the samples of `ddb/ddi` soundbanks.

## Requirements
```
pip install -r requirements.txt
```

## Examples
```
python ./extract_wav.py --src_path ./XXX.ddb
python ./extract_ddi.py --src_path ./XXX.ddi
python ./rename_wav.py --work_dir ./XXX
```

FRM2 files are not necessary for the wav workflow, so only run the following command if you have special desire for the extracted frm2 files:  
```
python ./extract_frm2.py --src_path ./XXX.ddb
```

## Guide for Python Beginners
1. Download and install [miniconda](https://docs.conda.io/en/latest/miniconda.html)  
   At the end installation, remember to set `conda init` as yes (or run it manually).
2. Create a python 3.10 environment by running `conda create -n py310 python=3.10`
3. Activate your new environment: `conda activate py310`
4. Install the required dependencies: `pip install pyyaml`
5. Run the scripts following the previous example!

## Usage:

```
usage: extract_ddi.py [-h] --src_path SRC_PATH

optional arguments:
  -h, --help           show this help message and exit
  --src_path SRC_PATH  source ddi file path
  --save_temp          save temp files
  --cat_only           only concat ddi.yml, assuming temp files exist.
```

```
usage: extract_wav.py [-h] --src_path SRC_PATH [--dst_path DST_PATH] [--filename_style {flat,devkit}]

options:
  -h, --help            show this help message and exit
  --src_path SRC_PATH   source ddi file path
  --dst_path DST_PATH   destination extract path, default to be "./[name]/snd"
  --filename_style {flat,devkit}
                        output filename style, default to be 'devkit'.
```

```
usage: extract_frm2.py [-h] --src_path SRC_PATH [--dst_path DST_PATH]

optional arguments:
  -h, --help           show this help message and exit
  --src_path SRC_PATH  source ddb file path
  --dst_path DST_PATH  destination extract path, default to be "./[name]/frm2.zip"
```

```
usage: pack_ddb.py [-h] --src_path SRC_PATH [--dst_path DST_PATH]

options:
  -h, --help           show this help message and exit
  --src_path SRC_PATH  singer tree file path
  --dst_path DST_PATH  destination path, default to be "./[singer name]"
```

```
usage: mixins_ddb.py [-h] --src_path SRC_PATH --mixins_path MIXINS_PATH [--dst_path DST_PATH] [--mixins_items MIXINS_ITEMS]                                                                                     

options:
  -h, --help            show this help message and exit
  --src_path SRC_PATH   source ddi file path
  --mixins_path MIXINS_PATH
                        the mixins ddi file path
  --dst_path DST_PATH   output folder, default to be "./[singer name]/mixins"
  --mixins_items MIXINS_ITEMS
                        mixins items, separated by ","default to be "vqm", currently only support "vqm"
```

# ddi.yml
`ddi.yml` file strucutre:
```
{
  'vqm': {
          'vqm': [
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
          ],
          }

  'sta': {
          'phoneme': [
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
          ],
          'phoneme': [
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
          ],
          }

  'art': {
          'phoneme[space]phoneme': [
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
          ],
          'phoneme[space]phoneme': [
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
          ],
          'phoneme[space]phoneme[space]phoneme': [
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
              {'snd': XXX, 'epr': [XXX,XXX,...]},
          ],
          }
}
```

# Generate vvd
[VVD Editor Pro](https://vvd.uselessbug.tk/en/)