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

import faiss
import numpy as np

from tools.retro.pretraining.query import (
    get_index as get_new_index,
    # get_banned_chunk_map,
    # query_embeddings,
)
from tools.retro.utils import get_gpt_tokenizer

from .align import get_pickle_hash
from .print_tokens import print_tokens

# >>>
from lutil import pax
# <<<

tokenizer = None
def tokens2str(ts):
    global tokenizer
    if not tokenizer:
        tokenizer = get_gpt_tokenizer()
    return "\\n".join(tokenizer.detokenize(ts).splitlines())[:125]

def query_chunk(meta, query_token_ids, index, db_ds):
    query_text = meta.tokenizer.detokenize(query_token_ids)
    query_embed = meta.embedder.embed_text(query_text)
    D, I = index.search(query_embed.reshape((1, -1)), 10)
    print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    print("QUERY : %s" % tokens2str(query_token_ids))
    for i, ni in enumerate(I[0]):
        print("NBR [%.3f] : %s" % (D[0][i].item(), tokens2str(db_ds[ni]["text"])))

def index_encode_chunks(meta, token_ids_0, token_ids_1, index, db_ds):

    text0 = meta.tokenizer.detokenize(token_ids_0)
    text1 = meta.tokenizer.detokenize(token_ids_1)
    embed0 = meta.embedder.embed_text(text0)
    embed1 = meta.embedder.embed_text(text1)
    embeds = np.vstack([ embed0.reshape((1, -1)), embed1.reshape((1, -1)) ])

    # pax({"embeds": embeds})

    index_ivf = faiss.extract_index_ivf(index)
    quantizer = index_ivf.quantizer

    # ef_search = 16
    # ef_search = 32
    ef_search = 64
    # ef_search = 128
    faiss.ParameterSpace().set_index_parameter(quantizer, "efSearch", ef_search)
    # faiss.ParameterSpace().set_index_parameter(quantizer, "nprobe", 4096)

    D, I = quantizer.search(embeds, 1024) # 100, 4096
    clusters0 = list(I[0, :])
    clusters1 = list(I[1, :])
    intsec = set(clusters0) & set(clusters1)

    # print(I)
    # print("CLUSTERS0 : %s." % clusters0)
    # print("CLUSTERS1 : %s." % clusters1)
    # print("INTSEC    : %s." % (set(clusters0) & set(clusters1)))
    pax({
        "clusters0" : "%d / %s" % (len(clusters0), str(clusters0)),
        "clusters1" : "%d / %s" % (len(clusters1), str(clusters1)),
        "intsec" : "%d / %s" % (len(intsec), str(intsec)),
    })
    pax({
        "index" : index,
        "index_ivf" : index_ivf,
        "quantizer" : quantizer,
        # "result" : result,
    })

# def print_nbrs(
#         meta,
#         sample_idxs,
#         chunk_idx,
#         old_db_ds,
#         new_db_ds,
#         old_sample,
#         new_sample,
#         db_hashes,
# ):
def print_nbrs(
        meta,
        old_pt_ds,
        new_pt_ds,
        old_sample_idx,
        new_sample_idx,
        chunk_idx,
        db_hashes,
):

    old_sample = old_pt_ds[old_sample_idx]
    new_sample = new_pt_ds[new_sample_idx]
    old_db_ds = old_pt_ds.db_ds
    new_db_ds = new_pt_ds.db_chunk_dataset

    # pax({
    #     "old_sample" : old_sample,
    #     "new_sample" : new_sample,
    # })

    tokenizer = meta.tokenizer
    embedder = meta.embedder
    nnbrs = meta.nnbrs
    chunk_length = meta.chunk_length
    n_chunks_per_seq = meta.n_chunks_per_seq

    # Extract sample.
    old_seq = old_sample["text"][:2048]
    new_seq = new_sample["text"][:2048]
    old_nbrs = old_sample["neighbor_tokens"][:, :, :meta.chunk_length]
    new_nbrs = new_sample["neighbor_tokens"][:, :, :meta.chunk_length]
    assert old_nbrs.shape == (n_chunks_per_seq, nnbrs, chunk_length)
    assert new_nbrs.shape == (n_chunks_per_seq, nnbrs, chunk_length)

    # Sample chunk.
    # old_seq_chunk = old_seq[
    #     (chunk_idx * chunk_length):((chunk_idx + 1) * chunk_length)]
    # new_seq_chunk = new_seq[
    #     (chunk_idx * chunk_length):((chunk_idx + 1) * chunk_length)]
    # assert get_pickle_hash(old_seq_chunk.tolist()) == \
    #     get_pickle_hash(new_seq_chunk.tolist())
    sample_chunk = old_seq[(chunk_idx*chunk_length):((chunk_idx+1)*chunk_length)]

    # pax({
    #     "sample chunk" : str(sample_chunk),
    #     "new sample chunks" : str(new_pt_ds.chunk_dataset[new_sample_idx * n_chunks_per_seq + chunk_idx]["text"]),
    # })

    # Neighbor chunks, tokens.
    old_nbr_chunk_ids = []
    new_nbr_chunk_ids = []
    old_nbr_token_ids = []
    new_nbr_token_ids = []
    for nbr_idx in range(nnbrs):
        old_nbr_chunk_ids.append(
            old_sample["neighbor_chunks"][chunk_idx][nbr_idx].item())
        new_nbr_chunk_ids.append(
            new_sample["neighbor_chunks"][chunk_idx][nbr_idx][0].item())
        old_nbr_token_ids.append(old_nbrs[chunk_idx][nbr_idx])
        new_nbr_token_ids.append(new_nbrs[chunk_idx][nbr_idx])

    # pax({
    #     "old_nbr_chunk_ids" : old_nbr_chunk_ids,
    #     "new_nbr_chunk_ids" : new_nbr_chunk_ids,
    # })
    
    # Hashes [ +acc ].
    old_nbr_hashes = [ get_pickle_hash(ts.tolist()) for ts in old_nbr_token_ids ]
    new_nbr_hashes = [ get_pickle_hash(ts.tolist()) for ts in new_nbr_token_ids ]
    common_nbr_hashes = set(old_nbr_hashes) & set(new_nbr_hashes)
    acc = len(common_nbr_hashes) / nnbrs

    # Embeddings, dists.
    sample_embed = embedder.embed_text(tokenizer.detokenize(sample_chunk))
    old_nbr_embeds = [ embedder.embed_text(tokenizer.detokenize(ts))
                       for ts in old_nbr_token_ids ]
    new_nbr_embeds = [ embedder.embed_text(tokenizer.detokenize(ts))
                       for ts in new_nbr_token_ids ]
    old_nbr_dists = [ np.linalg.norm(sample_embed - e) for e in old_nbr_embeds ]
    new_nbr_dists = [ np.linalg.norm(sample_embed - e) for e in new_nbr_embeds ]

    causal = True
    # if accs[-1] == 0.9 and old_nbr_hashes[0] not in new_nbr_hashes:
    # if True:
    if acc != 1:
        causal = False

        header = "############## sample %s, chunk %d ##############" % (
            ",".join(str(i) for i in set([old_sample_idx, new_sample_idx])),
            chunk_idx,
        )
        print()
        print("#" * len(header))
        print(header)
        print("#" * len(header))
        # print_tokens("OLD_CHUNK", old_seq_chunk)
        # print_tokens("NEW_CHUNK", new_seq_chunk)
        print_tokens("SAMPLE", sample_chunk)
        print("DOC_IDS : %s." % str(new_sample["doc_ids"]))

        print()
        for i, ts in enumerate(old_nbr_token_ids): # [:2]):
            # doc_id = 
            c = old_nbr_hashes[i] in common_nbr_hashes
            print("[%d] %.3f, %s : %s" % (
                old_db_ds[old_nbr_chunk_ids[i]]["doc_id"],
                old_nbr_dists[i],
                "  OLD  " if c else "[[OLD]]",
                # "\\n".join(tokenizer.detokenize(ts[:30]).splitlines()),
                tokens2str(ts),
                # "\\n".join(tokenizer.detokenize(ts).splitlines()),
            ))
        print()
        for i, ts in enumerate(new_nbr_token_ids): # [:2]):
            c = new_nbr_hashes[i] in common_nbr_hashes
            print("[%d] %.3f, %s : %s" % (
                new_db_ds[new_nbr_chunk_ids[i]]["doc_id"],
                new_nbr_dists[i],
                "  NEW  " if c else "[[NEW]]",
                # "\\n".join(tokenizer.detokenize(ts[:30]).splitlines()),
                tokens2str(ts),
                # "\\n".join(tokenizer.detokenize(ts).splitlines()),
            ))

        print()
        print("ACC : %.2f." % (100 * acc))
        print("DISTS : old %.4f, new %.4f." % (
            np.mean(old_nbr_dists), # [1:]), # skip causality bug.
            np.mean(new_nbr_dists), # [1:]),
        ))

    # >>>
    # print("load old index.")
    # old_index = faiss.read_index("/gpfs/fs1/projects/gpu_adlr/datasets/boxinw/processed_data/chunks/Wikipedia_IVF262144_HNSW32_Flat_index.bin", faiss.IO_FLAG_MMAP)
    # print("load new index.")
    # new_index = get_new_index(new_db_ds, ondisk = True)
    # print("finished loading indexes.")
    # ef_search = 16
    # # ef_search = 32
    # # ef_search = 64
    # # ef_search = 128
    # faiss.ParameterSpace().set_index_parameter(old_index, "efSearch", ef_search)
    # faiss.ParameterSpace().set_index_parameter(old_index, "nprobe", 4096)
    # faiss.ParameterSpace().set_index_parameter(new_index, "efSearch", ef_search)
    # faiss.ParameterSpace().set_index_parameter(new_index, "nprobe", 4096)

    # pax({
    #     "new_index" : new_index,
    #     "new_index / ivf" : faiss.extract_index_ivf(new_index),
    #     "new_index / ivf / quantizer" :
    #     faiss.extract_index_ivf(new_index).quantizer,
    #     # "ef-search" :
    #     # faiss.ParameterSpace().get_index_parameter(index, "efSearch"),
    # })

    # missing_old_nbr_idxs = [ i for i in range(nnbrs)
    #                          if old_nbr_hashes[i] not in new_nbr_hashes ]

    # # query_chunk(meta, sample_chunk, old_index, old_db_ds)
    # # query_chunk(meta, sample_chunk, new_index, new_db_ds)
    # # query_chunk(meta, old_nbr_token_ids[missing_old_nbr_idxs[0]],
    # #             new_index, new_db_ds)
    # # query_chunk(meta, old_nbr_token_ids[missing_old_nbr_idxs[0]],
    # #             old_index, old_db_ds)

    # index_encode_chunks(
    #     meta,
    #     sample_chunk,
    #     old_nbr_token_ids[missing_old_nbr_idxs[0]],
    #     old_index, old_db_ds,
    #     # new_index, new_db_ds,
    # )
    # pax({})
    # for nidx in range(nnbrs):
    #     if old_nbr_hashes[nidx] in new_nbr_hashes:
    #         raise Exception("hi.")
    #         continue
    #     query_chunk(old_nbr_token_ids[nidx], new_index, new_db_ds)
    #     break
    # for nidx in range(nnbrs):
    #     if old_nbr_hashes[nidx] in new_nbr_hashes:
    #         raise Exception("hi.")
    #         continue
    #     D, I = new_index.search(sample_embed.reshape((1, -1)), 10)
    #     print("QUERY : %s" % tokens2str(sample_chunk))
    #     for i, ni in enumerate(I[0]):
    #         print("NBR [%.3f] : %s" % (D[0][i].item(), tokens2str(new_db_ds[ni]["text"])))
    #     pax({
    #         "I" : str(I),
    #     })
    # <<<

    # >>>
    # if accs[-1] == 0.9 and old_nbr_hashes[0] not in new_nbr_hashes:
    if False:
    # if acc != 1:
        try:
            diff_index = min(i for i in range(nnbrs)
                             if old_nbr_hashes[i] != new_nbr_hashes[i])
        except:
            pax({
                "old_nbr_hashes" : old_nbr_hashes,
                "new_nbr_hashes" : new_nbr_hashes,
            })
        # old_nbr_id = db_hashes.old[old_nbr_hashes[diff_index]]
        # new_nbr_id = db_hashes.new[new_nbr_hashes[diff_index]]
        pax(0, {
            "banned doc ids" : str(new_sample["doc_ids"]),
            "diff_index" : diff_index,
            "old diff hash" : old_nbr_hashes[diff_index],
            # "old diff in old db?" : old_nbr_hashes[diff_index] in db_hashes.old,
            # "old diff in new db?" : old_nbr_hashes[diff_index] in db_hashes.new,
            # "old_nbr_id" : old_nbr_id,
            # "new_nbr_id" : new_nbr_id,
            # "old nbr" : "%d / %s" % (
            #     old_db_ds[old_nbr_id]["doc_id"],
            #     str(old_db_ds[old_nbr_id]["text"]),
            # ),
            # "new nbr" : "%d / %s" % (
            #     new_db_ds[new_nbr_id]["doc_id"],
            #     str(new_db_ds[new_nbr_id]["text"]),
            # ),

            # "seq_embed" : seq_embed,
            # "old_nbr_embeds" : old_nbr_embeds,
            # "new_nbr_embeds" : new_nbr_embeds,
            "old_nbr_dists" : str(old_nbr_dists),
            "new_nbr_dists" : str(new_nbr_dists),
        })
    # <<<

    return acc, causal, np.mean(old_nbr_dists), np.mean(new_nbr_dists)

# def _print_pt_neighbors(
# def print_pt_neighbors(
#         gpt_tokenizer,
#         embedder,
#         chunk_length,
#         nnbrs,
#         n_chunks_per_seq,
#         old_pt_ds,
#         new_pt_ds,
#         pt_hashes,
#         # db_hashes,
# ):

#     accs = []
#     n_causal = 0

#     old_pt_hash_map = pt_hashes["old"]
#     new_pt_hash_map = pt_hashes["new"]
#     common_pt_hashes = pt_hashes["common"]
#     # for sample_idx in range(10): # range(10, 20):
#     # for pt_hash_idx in range(
#     #         0,
#     #         len(common_pt_hashes),
#     #         max(1, len(common_pt_hashes) // 1000),
#     # ):
#     for rand_idx in range(100):

#         pt_hash_idx = np.random.randint(len(common_pt_hashes))

#         pt_hash = common_pt_hashes[pt_hash_idx]
#         old_sample_idx = old_pt_hash_map[pt_hash]
#         new_sample_idx = new_pt_hash_map[pt_hash]
#         sample_idxs = list(set([ old_sample_idx, new_sample_idx ]))

#         old_seq = old_pt_seqs_train[old_sample_idx]
#         new_sample = new_pt_retro_train_ds[new_sample_idx]
#         new_seq = new_sample["text"]

#         old_nbr_ids = old_pt_nbrs_train[old_sample_idx][:, :nnbrs]
#         new_nbrs = new_sample["neighbor_tokens"]
#         assert nnbrs == new_nbrs.shape[1]

#         # for chunk_idx in range(n_chunks_per_seq):
#         chunk_idx = np.random.randint(n_chunks_per_seq)

#         print_nbrs(chunk_idx)

#     # acc = np.mean(accs)
#     # causal_rate = n_causal
#     pax(0, {
#         "n_acc" : len(accs),
#         "n_causal" : n_causal,
#         "acc" : np.mean(accs),
#         "causal" : n_causal / len(accs),
#     })
def print_pt_neighbors(
        meta,
        old_pt_ds,
        new_pt_ds,
        pt_hashes,
        db_hashes,
):

    accs = []
    n_causal = 0
    old_dists = []
    new_dists = []

    # old_pt_hash_map = pt_hashes["old"]
    # new_pt_hash_map = pt_hashes["new"]
    # common_pt_hashes = pt_hashes["common"]
    for rand_idx in range(100):

        # pt_hash_idx = np.random.randint(len(pt_hashes.common))
        # pt_hash = pt_hashes.common[pt_hash_idx]
        # old_sample_idx = pt_hashes.old[pt_hash]
        # new_sample_idx = pt_hashes.new[pt_hash]
        # pax({"pt_hashes": pt_hashes})
        pt_hash_idx = np.random.randint(len(pt_hashes.data)) # .old))
        # old_sample_idx = pt_hashes.old[pt_hash_idx].item()
        # new_sample_idx = pt_hashes.new[pt_hash_idx].item()
        old_sample_idx, new_sample_idx, pt_hash = \
            [ a.item() for a in pt_hashes.data[pt_hash_idx] ]

        # pax({
        #     "pt_hash_idx" : pt_hash_idx,
        #     "pt_hash" : pt_hash,
        #     "old_sample_idx" : old_sample_idx,
        #     "new_sample_idx" : new_sample_idx,
        # })

        sample_idxs = list(set([ old_sample_idx, new_sample_idx ]))

        old_sample = old_pt_ds[old_sample_idx]
        new_sample = new_pt_ds[new_sample_idx]

        # for chunk_idx in range(n_chunks_per_seq):
        chunk_idx = np.random.randint(meta.n_chunks_per_seq)

        # acc, causal, old_dist, new_dist = print_nbrs(
        #     meta,
        #     sample_idxs,
        #     chunk_idx,
        #     old_pt_ds.db_ds,
        #     new_pt_ds.db_chunk_dataset,
        #     old_sample,
        #     new_sample,
        #     db_hashes,
        # )
        acc, causal, old_dist, new_dist = print_nbrs(
            meta,
            old_pt_ds,
            new_pt_ds,
            old_sample_idx,
            new_sample_idx,
            chunk_idx,
            db_hashes,
        )
        accs.append(acc)
        n_causal += int(causal)
        old_dists.append(old_dist)
        new_dists.append(new_dist)

    # acc = np.mean(accs)
    # causal_rate = n_causal
    pax(0, {
        "n_acc" : len(accs),
        "n_causal" : n_causal,
        "acc" : np.mean(accs),
        "causal" : n_causal / len(accs),
        "old_dist" : np.mean(old_dists).item(),
        "new_dist" : np.mean(new_dists).item(),
    })
