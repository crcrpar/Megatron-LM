# coding=utf-8
# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# import glob
import h5py
# import joblib
import numpy as np
import os
from pathlib import Path
# import time
import torch
from tqdm import tqdm

# import sys
# sys.path.append("/home/boxinw-src/megatron-lm/megatron")
# sys.path.append("/home/boxinw-src/megatron-lm/")

# from megatron import get_args
# from megatron.data import indexed_dataset
from megatron.data.indexed_dataset import make_dataset as make_indexed_dataset
# from megatron.tokenizer import build_tokenizer

from .utils import get_single_chunk_index_path, get_concat_chunk_index_path

# >>>
from lutil import pax
# <<<

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# see: notebook/faiss/create_chunks.ipynb
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# def get_indexed_dataset_(data_prefix, data_impl, skip_warmup):
#     """Build indexed dataset."""
#     print(' > building dataset index ...')

#     start_time = time.time()
#     indexed_dataset = make_indexed_dataset(data_prefix,
#                                            data_impl,
#                                            skip_warmup)
#     print(' > finished creating indexed dataset in {:4f} '
#                  'seconds'.format(time.time() - start_time))
#     print('    number of documents: {}'.format(
#         indexed_dataset.sizes.shape[0]))

#     return indexed_dataset

# def get_database_and_index(indexed_dataset):

#     size = indexed_dataset.sizes.shape[0]
#     train = int(round(float(size) * 0.98))
#     tot = 0

#     databases = []
#     indexes = []

#     for document_id, document in enumerate(tqdm(indexed_dataset)):
#         if document_id == train:
#             break
#         eod = document[-1]
#         document = document[:-1]
#         token_no = len(document)
#         tot += token_no
#         chunks = int(np.ceil(token_no / 64))

#         for i in range(chunks):
#             tokens = document[i * 64:(i+1) *64]
#             if len(tokens) < 64:
#                 pad = np.array([eod] * (64 - len(tokens)), dtype='uint16')
#                 tokens = np.hstack((tokens, pad))
#             assert len(tokens) == 64
#             databases.append(tokens)
#             indexes.append(document_id)
#     return databases, indexes
# def build_single_chunk_index(args, indexed_dataset):
def build_chunk_index(args, indexed_dataset):

    size = indexed_dataset.sizes.shape[0]
    train = int(round(float(size) * 0.98))

    # eods = []
    chunk_index = []

    for document_id, document in enumerate(tqdm(indexed_dataset)):

        # >>>
        # if document_id == 1000:
        #     break
        # <<<

        if document_id == train:
            break

        eod = document[-1]
        document = document[:-1]
        document_len = len(document)

        chunk_start_idxs = list(range(0, document_len, args.retrieval_chunk_len))
        chunk_end_idxs = [min(document_len, s + args.retrieval_chunk_len)
                          for s in chunk_start_idxs]

        # eods.append(eod)
        chunk_index.extend([(document_id, *idxs)
                            for idxs in zip(chunk_start_idxs, chunk_end_idxs)])

    print(' > converting chunk index to numpy.')
    # eods = np.array(eods)
    chunk_index = np.array(chunk_index)

    # return eods, chunk_index
    return chunk_index

# def dump_document_order():
def save_document_order(args, workdir):

    assert torch.distributed.get_rank() == 0, "single process operation."

    # args = get_args()

    # Data files.
    # # data_files = [ prefix.rstrip("/") + ".bin" for prefix in args.data_path ]
    # pax({"data_files": data_files})
    # data_files = [ path for path in data_files if os.path.exists(path) ]
    # data_prefixes = [ os.path.splitext(f)[0] for f in data_files ]
    # data_names = [ Path(f).stem for f in data_files ]

    assert len(args.data_path) % 2 == 0, \
        "currently, only blendable dataset is supported."
    data_metas = []
    for i in range(0, len(args.data_path), 2):
        ratio = float(args.data_path[i])
        prefix = args.data_path[i + 1]
        path = prefix + ".bin"
        name = os.path.basename(prefix)
        assert os.path.exists(path)
        data_metas.append({
            "ratio" : ratio,
            "prefix" : prefix,
            "path" : path,
            "name" : name,
            "chunk_index_path" : get_single_chunk_index_path(workdir, name)
        })

    # pax({
    #     "data_metas" : data_metas,
    #     "data_metas / 0" : data_metas[0],
    # })

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # create_data_softlinks(data_files)
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # Build chunk indexes.
    # for data_index, data_file in enumerate(data_files):
    #     data_name = data_names[data_index]
    #     data_prefix = data_prefixes[data_index]
    #     chunk_index_file = ?
    for data_index, data_meta in enumerate(data_metas):

        data_name = data_meta["name"]
        data_prefix = data_meta["prefix"]
        chunk_index_path = data_meta["chunk_index_path"]

        if os.path.exists(chunk_index_path):
            continue

        print(" > creating chunk index, dataset %d / %d ... '%s'." %
              (data_index, len(data_metas), data_name))

        indexed_dataset = make_indexed_dataset(data_prefix, "mmap", True)
        chunk_index = build_chunk_index(args, indexed_dataset)

        print(" > saving chunk index.")

        f = h5py.File(chunk_index_path, "w")
        # dset = f.create_dataset("eods", data=eods)
        dset = f.create_dataset("index", data=chunk_index)
        f.close()

        print(" > finished saving chunk index.")

    # Count total chunks.
    total_chunks = 0
    for data_index, data_meta in enumerate(data_metas):

        f = h5py.File(data_meta["chunk_index_path"], "r")
        total_chunks += len(f["index"])
        f.close()

        print(" > counting chunks, dataset %d / %d, total %d ... '%s'." %
              (data_index, len(data_metas), total_chunks, data_name))


    # Concatenated chunks index.
    chunk_index_path = get_concat_chunk_index_path(workdir)

    # Delete existing chunk index if incorrect size.
    if os.path.exists(chunk_index_path):

        raise Exception("concat chunks exist.")

        f = h5py.File(chunk_index_path)
        total_chunks_existing = len(f["index"])
        f.close()

        if total_chunks != total_chunks_existing:
            raise Exception("delete existing")
            os.remove(chunk_index_path)

    # Build concatenated chunk index.
    if not os.path.exists(chunk_index_path):

        raise Exception("concat chunk indexes.")

    pax({
        # "args" : args,
        "chunk_index_path" : chunk_index_path,
    })

    
    raise Exception("finished creating chunks.")

    # # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # # 5334816766
    # # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # ARX="ArXiv_ftfy_cleaned_id_shuf_text_document.chunks.hdf5"
    # BC2="BookCorpus2_ftfy_cleaned_id_shuf_text_document.chunks.hdf5"
    # B3="Books3_ftfy_cleaned_id_shuf_text_document.chunks.hdf5"
    # CC2020="CC-2020-50_id_cleaned_shuf_text_document.chunks.hdf5"
    # CC2021="CC-2021-04_id_cleaned_shuf_text_document.chunks.hdf5"
    # GIT="Github_ftfy_id_shuf_text_document.chunks.hdf5"
    # GUT="Gutenberg_PG-19_ftfy_cleaned_id_cleaned_shuf_text_document.chunks.hdf5"
    # NIH="NIH_ExPorter_ftfy_id_shuf_text_document.chunks.hdf5"
    # OWT2="OpenWebText2_ftfy_cleaned_id_shuf_text_document.chunks.hdf5"
    # PCC="Pile-CC_id_cleaned_shuf_text_document.chunks.hdf5"
    # PM="PubMed_Abstracts_ftfy_id_shuf_text_document.chunks.hdf5"
    # RN="rn_dedup_shuf_cleaned_0.7_cleaned_shuf_text_document.chunks.hdf5"
    # SE="StackExchange_ftfy_id_shuf_text_document.chunks.hdf5"
    # ST="stories_dedup0.7_shuf_cleaned_shuf_text_document.chunks.hdf5"
    # WIK="Wikipedia_en_ftfy_id_shuf_text_document.chunks.hdf5"

    # DATA_BLEND={B3: 0.14336,
    #             RN: 0.08962,
    #             OWT2: 0.19336,
    #             SE: 0.05689,
    #             ST: 0.00859,
    #             PM: 0.02897,
    #             WIK: 0.04771,
    #             GUT: 0.00873,
    #             BC2: 0.01007,
    #             NIH:0.00208,
    #             CC2020: 0.13017,
    #             PCC:  0.09446,
    #             CC2021: 0.15652,
    #             ARX: 0.01359,
    #             GIT: 0.01588
    #            }

    # orders = [(k, v) for k, v in DATA_BLEND.items()]

    # f = h5py.File("pretraining_corpus" + ".chunks.hdf5", "w")
    # dset = f.create_dataset("chunks", (tot,64), dtype="uint16")

    # dset.shape

    # # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # # (5334816766, 64)
    # # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # pointer = 0
    # for order in tqdm(orders):
    #     dataset = order[0]

    #     rf = h5py.File(dataset, "r")
    #     data = rf["chunks"]
    #     dset[pointer:pointer + len(data)] = data
    #     pointer += len(data)

    # f.close()

    # orders

    # # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # # [('Books3_ftfy_cleaned_id_shuf_text_document.chunks.hdf5', 0.14336),
    # #  ('rn_dedup_shuf_cleaned_0.7_cleaned_shuf_text_document.chunks.hdf5', 0.08962),
    # #  ('OpenWebText2_ftfy_cleaned_id_shuf_text_document.chunks.hdf5', 0.19336),
    # #  ('StackExchange_ftfy_id_shuf_text_document.chunks.hdf5', 0.05689),
    # #  ('stories_dedup0.7_shuf_cleaned_shuf_text_document.chunks.hdf5', 0.00859),
    # #  ('PubMed_Abstracts_ftfy_id_shuf_text_document.chunks.hdf5', 0.02897),
    # #  ('Wikipedia_en_ftfy_id_shuf_text_document.chunks.hdf5', 0.04771),
    # #  ('Gutenberg_PG-19_ftfy_cleaned_id_cleaned_shuf_text_document.chunks.hdf5',
    # #   0.00873),
    # #  ('BookCorpus2_ftfy_cleaned_id_shuf_text_document.chunks.hdf5', 0.01007),
    # #  ('NIH_ExPorter_ftfy_id_shuf_text_document.chunks.hdf5', 0.00208),
    # #  ('CC-2020-50_id_cleaned_shuf_text_document.chunks.hdf5', 0.13017),
    # #  ('Pile-CC_id_cleaned_shuf_text_document.chunks.hdf5', 0.09446),
    # #  ('CC-2021-04_id_cleaned_shuf_text_document.chunks.hdf5', 0.15652),
    # #  ('ArXiv_ftfy_cleaned_id_shuf_text_document.chunks.hdf5', 0.01359),
    # #  ('Github_ftfy_id_shuf_text_document.chunks.hdf5', 0.01588)]
    # # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # joblib.dump(orders, "order.pkl")

    # # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # # ['order.pkl']
    # # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # f = h5py.File("sampled_pretraining_corpus" + ".chunks.hdf5", "w")
    # sampled_tot = 300000000
    # dset = f.create_dataset("chunks", (sampled_tot,64), dtype="uint16")

    # pointer = 0
    # for order in tqdm(orders):
    #     dataset = order[0]
    #     ratio = order[1]
    #     size = int(round(float(sampled_tot) * ratio))

    #     rf = h5py.File(dataset, "r")
    #     data = rf["chunks"]
    #     dset[pointer:pointer + size] = data[:size]
    #     pointer += size

    # f.close()

    # f = h5py.File("pretraining_corpus" + ".chunks.hdf5", "r")

    # f['chunks'][2323453]

    # # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # # array([  547, 20467, 45427,    13,   632,   561,  1011,  4647,   284,
    # #        30282,   262,  3580,  1022,  3288,   290,  7593,  4808,  7645,
    # #           62, 27997,    13,  1892, 12362,    11,   262,  3288,  4808,
    # #         7645,    62, 27997,   287,  9215,  2900,   503,   284,   307,
    # #        13205,    11,  9472,   262,  7593,   318, 21499,  2728,  2279,
    # #          422,  4890,   284,  2612,  4369,   284, 47906, 15885,   198,
    # #          198,  1135,   783,   760,   326, 23426,   960,  8201,  5384,
    # #          960], dtype=uint16)
    # # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # f['chunks'].shape

    # # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # # (5334816766, 64)
    # # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # raise Exception("it worked?")

# eof
