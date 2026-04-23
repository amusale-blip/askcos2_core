import os
import time
import json
import gzip
import hashlib
import pandas as pd
import numpy as np
from bson import Binary, ObjectId, json_util
from tqdm import tqdm
from configs import db_config
from fastapi import Query
from pymongo import errors, MongoClient
from pymongo.collection import ReturnDocument
from rdkit import Chem
from rdkit.Chem import AllChem, rdqueries, rdMolDescriptors
from typing import Annotated, Any
from utils import register_util
from utils.similarity_search_utils import sim_search_aggregate_buyables, sim_search_buyables
from utils.pricer_utils import abs_smiles_to_smarts_query, ATOM_DICT
from utils.rdkit import has_abs_groups


global util_config


def substructure_match(input_data):
    doc, query = input_data
    rdmol = Chem.Mol(doc["mol"])
    if rdmol.HasSubstructMatch(query, useChirality=True):
        return True
    else:
        return False


@register_util(name="pricer")
class Pricer:
    """Util class for Pricer, to be used as a controller (over Mongo/FilePricer)"""
    prefixes = ["pricer"]
    methods_to_bind: dict[str, list[str]] = {
        "lookup_smarts": ["POST"],
        "lookup_smiles": ["POST"],
        "abs_smiles_to_smarts_query": ["POST"]
    }
    # methods_to_bind: dict[str, list[str]] = {
    #     "lookup_smiles": ["POST"],
    #     "lookup_smiles_list": ["POST"],
    #     "lookup_smarts": ["POST"],
    #     "search": ["POST"],
    #     "list_sources": ["GET"],
    #     "list_properties": ["GET"],
    #     "get": ["GET"],
    #     "add": ["POST"],
    #     "add_many": ["POST"],
    #     "update": ["POST"],
    #     "delete": ["DELETE"]
    # }

    def __init__(self, util_config: dict[str, Any]):
        engine = util_config["engine"]
        if engine == "db":
            self._pricer = MongoPricer(
                config=db_config.MONGO,
                database=util_config["database"],
                collection=util_config["collection"],
                buyables_cache_dir=util_config.get("buyables_cache_dir"),
                preload_buyables=util_config.get("preload_buyables", False),
            )
            self.collection = self._pricer.collection
        elif engine == "file":
            self._pricer = FilePricer(
                path=util_config["file"],
                precompute_mols=util_config["precompute_mols"]
            )
        else:
            raise ValueError(f"Unsupported pricer engine: {engine}! "
                             f"Only 'db' or 'file' is supported")

    @staticmethod
    def canonicalize(smiles: str, isomeric_smiles: bool = True):
        """
        Canonicalize the input SMILES.

        Returns:
            str: canonicalized SMILES or empty str on failure
        """
        try:
            mol = Chem.MolFromSmiles(smiles)
            smiles = Chem.MolToSmiles(mol, isomericSmiles=isomeric_smiles)
        except Exception:
            return ""
        else:
            return smiles

    def lookup_smiles(
        self,
        smiles: str,
        source: Annotated[list[str] | None, Query()] = None,
        canonicalize: bool = True,
        isomeric_smiles: bool = True
    ) -> dict | None:
        """
        Lookup data for the requested SMILES, based on lowest price.

        Args:
            smiles (str): SMILES string to look up
            source (list or str, optional): buyables sources to consider;
                if ``None`` (default), include all sources, otherwise
                must be single source or list of sources to consider;
            canonicalize (bool, optional): whether to canonicalize SMILES string
            isomeric_smiles (bool, optional): whether to generate isomeric
                SMILES string when performing canonicalization

        Returns:
            dict: data for the requested SMILES, None if not found
        """
        if canonicalize:
            smiles = self.canonicalize(
                smiles=smiles,
                isomeric_smiles=isomeric_smiles
            ) or smiles

        return self._pricer.lookup_smiles(smiles=smiles, source=source)

    def lookup_smiles_list(
        self,
        smiles_list: list[str],
        source: list[str] | str | None = None,
        canonicalize: bool = True,
        isomeric_smiles: bool = True
    ) -> dict | None:
        """
        Lookup data for a list of SMILES, based on lowest price for each.

        SMILES not found in database are omitted from the output dict.

        Args:
            smiles_list (list): list of SMILES strings to look up
            source (list or str, optional): buyables sources to consider;
                if ``None`` (default), include all sources, otherwise
                must be single source or list of sources to consider;
            canonicalize (bool, optional): whether to canonicalize SMILES string
            isomeric_smiles (bool, optional): whether to generate isomeric
                SMILES string when performing canonicalization

        Returns:
            dict: mapping from input SMILES to data dict
        """
        if canonicalize:
            smiles_list = [
                self.canonicalize(smi, isomeric_smiles=isomeric_smiles) or smi
                for smi in smiles_list
            ]

        return self._pricer.lookup_smiles_list(smiles_list=smiles_list, source=source)

    def lookup_smarts(
        self,
        smarts: str,
        limit: int | None = None,
        precomputed_mols: bool = False, 
        version: str = 'default',
        max_ppg: float | None = None,
        convert_smiles: bool = False
    ) -> list | dict:

        return self._pricer.lookup_smarts(
            smarts=smarts,
            limit=limit,
            precomputed_mols=precomputed_mols, 
            version=version,
            max_ppg=max_ppg,
            convert_smiles=convert_smiles
        )

    # The following methods are Mongo only
    def search(
        self,
        search_str: str,
        source: list[str] | str | None = None,
        properties: list[dict[str, Any]] = None,
        regex: bool = False,
        sim_threshold: float = 1.0,
        limit: int = 100,
        canonicalize: bool = True,
        isomeric_smiles: bool = True,
        similarity_method: str = "accurate",
    ) -> list:
        """
        Search the database based on the specified criteria.

        Returns:
            list: full documents of all buyables matching the criteria
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"search() is only implemented for MongoPricer"

        query = {}
        tanimoto_similarities = None
        keys_to_keep = [
            "_id", "smiles", "ppg", "lead_time", "source", "properties", "tanimoto"
        ]
        db_comparison_map = {
            ">": "$gt", ">=": "$gte", "<": "$lt", "<=": "$lte", "==": "$eq"
        }

        if search_str:
            if regex:
                version = "preloaded" if self._pricer.preload_buyables else "default"
                convert = has_abs_groups(search_str)
                smarts_lookup_res = self.lookup_smarts(
                    smarts=search_str,
                    limit=limit,
                    version=version,
                    convert_smiles=convert,
                )
                smiles_matches = [d["smiles"] for d in smarts_lookup_res][:limit]
                query["smiles"] = {"$in": smiles_matches}
            elif sim_threshold == 1:
                if canonicalize:
                    search_str = (
                        self.canonicalize(search_str, isomeric_smiles=isomeric_smiles)
                        or search_str
                    )
                query["smiles"] = search_str
            else:
                similarity_results = self._pricer.lookup_similar_smiles(
                    smiles=search_str,
                    sim_threshold=sim_threshold,
                    method=similarity_method,
                    limit=limit
                )
                tanimoto_similarities = {
                    r["smiles"]: r["tanimoto"] for r in similarity_results
                }
                smiles_matches = list(tanimoto_similarities.keys())
                query["smiles"] = {"$in": smiles_matches}

        if source is not None:
            query["source"] = {"$in": self._pricer._source_to_query(source)}

        if properties is not None:
            property_query = []
            for item in properties:
                property_query.append(
                    {
                        "properties": {
                            "$elemMatch": {
                                "name": item["name"],
                                "value": {
                                    db_comparison_map[item["logic"]]: item["value"]
                                },
                            }
                        }
                    }
                )
            query["$and"] = property_query

        search_result = list(
            self.collection.find(query, projection=keys_to_keep).limit(limit)
        )

        for doc in search_result:
            doc["_id"] = str(doc["_id"])
            if tanimoto_similarities:
                doc["tanimoto"] = "{:.2f}".format(tanimoto_similarities[doc["smiles"]])

        if tanimoto_similarities:
            search_result = sorted(
                search_result, key=lambda x: x["tanimoto"], reverse=True
            )

            def key_switch(item):
                tanimoto = item["tanimoto"]
                item["similarity"] = tanimoto
                del item["tanimoto"]
                return item
            search_result = list(map(key_switch, search_result))
            # print(search_result)

        for res in search_result:
            properties= res.get("properties")
            if properties is None: properties = []
            new_properties = []            
            for prop in properties:
                key, value = list(prop.items()).pop()
                new_properties.append(
                    {"name": key,
                     "value": value}
                )
            res["properties"] = new_properties
            if res.get("similarity") is None:
                res["similarity"] = str(sim_threshold)
        
        return search_result

    def list_sources(self) -> list[str]:
        """
        Retrieve all available source names.

        Returns:
            list: list of source names
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"list_sources() is only implemented for MongoPricer"

        sources = [s for s in self.collection.distinct("source") if s]
        if (
            self.collection.find_one(filter={"source": {"$in": [None, ""]}})
            is not None
        ):
            sources.append("none")

        return sources

    def list_properties(self) -> list[str]:
        """
        Retrieve all available property names.

        Note: Not all documents may have all properties defined.

        Returns:
            list: list of property names
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"list_properties() is only implemented for MongoPricer"

        return list(self.collection.distinct("properties.name"))

    def get(self, _id: str) -> dict:
        """
        Get a single entry by its _id.
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"get() is only implemented for MongoPricer"

        # result = self.collection.find_one({"_id": ObjectId(_id)})
        result = self.collection.find_one({"_id": _id})
        if result and result.get("_id"):
            result["_id"] = str(result["_id"])

        return result

    def update(self, _id: str, new_doc: dict) -> dict:
        """
        Update a single entry by its _id.
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"update() is only implemented for MongoPricer"

        result = self.collection.find_one_and_replace(
            {"_id": ObjectId(_id)}, new_doc, return_document=ReturnDocument.AFTER
        )
        if result and result.get("_id"):
            result["_id"] = str(result["_id"])

        return result

    def delete(self, _id: str) -> bool:
        """
        Delete a single entry by its _id.
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"delete() is only implemented for MongoPricer"

        delete_result = self.collection.delete_one({"_id": _id})
        # delete_result = self.collection.delete_one({"_id": ObjectId(_id)})

        return delete_result.deleted_count > 0

    def add(self, new_doc: dict, allow_overwrite: bool = True) -> dict:
        """
        Add a new entry to the database.
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"add() is only implemented for MongoPricer"

        new_doc["smiles"] = self.canonicalize(new_doc["smiles"])
        smi, source = new_doc["smiles"], new_doc["source"]
        smi_vendor = f"{smi}{source}"
        hash_id = hashlib.sha256(smi_vendor.encode('utf-8')).hexdigest()
        new_doc["_id"] = hash_id
        result = {"doc": None, "updated": False, "error": None}
        query = {
            "smiles": new_doc["smiles"],
            "source": new_doc["source"],
        }
        existing_doc = self.collection.find_one(query)
        if existing_doc:
            if allow_overwrite:
                replace_result = self.collection.replace_one(query, new_doc)
                if replace_result.matched_count:
                    new_doc["_id"] = str(existing_doc["_id"])
                    result["doc"] = new_doc
                    result["updated"] = True
                else:
                    result["error"] = "Failed to update buyable entry."
        else:
            insert_result = self.collection.insert_one(new_doc)
            if insert_result.inserted_id:
                new_doc["_id"] = str(insert_result.inserted_id)
                result["doc"] = new_doc
            else:
                result["error"] = "Failed to add buyable entry."

        return result

    def add_many(self, new_docs: list[dict], allow_overwrite: bool = True) -> dict:
        """
        Add a list of new entries to the database.
        """

        assert isinstance(self._pricer, MongoPricer), \
            f"add_many() is only implemented for MongoPricer"

        result = {
            "error": None,
            "inserted": [],
            "updated": [],
            "inserted_count": 0,
            "updated_count": 0,
            "duplicate_count": 0,
            "error_count": 0,
            "total_count": len(new_docs),
        }

        for new_doc in new_docs:
            res = self.add(new_doc, allow_overwrite=allow_overwrite)
            if not res["error"]:
                if res["doc"]:
                    if res["updated"]:
                        result["updated"].append(res["doc"])
                        result["updated_count"] += 1
                    else:
                        result["inserted"].append(res["doc"])
                        result["inserted_count"] += 1
                else:
                    result["duplicate_count"] += 1
            else:
                result["error"] = res["error"]
                result["error_count"] += 1

        return result
        
    def abs_smiles_to_smarts_query(self, smiles: str) -> list[str]:
        return self._pricer.abs_smiles_to_smarts_query(smiles=smiles)


class MongoPricer:
    def __init__(
        self,
        config: dict,
        database: str,
        collection: str,
        preload_buyables: bool = False,
        buyables_cache_dir: str | None = None,
    ):
        """
        Initialize database connection.

        Args:
            buyables_cache_dir: Root directory for on-disk buyables preload cache.
                If unset or empty, uses ``configs.db_config.BUYABLES_CACHE_DIR``
                (from env ``BUYABLES_CACHE_DIR`` or default).
        """
        # print(config, database, collection)
        self.client = MongoClient(serverSelectionTimeoutMS=1000, **config)

        try:
            self.client.server_info()
        except errors.ServerSelectionTimeoutError:
            raise ValueError("Cannot connect to mongodb to load prices")
        else:
            self.collection = self.client[database][collection]
            self.dedup_collection_str = "buyables_to_preload"
            self.dedup_collection = self.client[database][self.dedup_collection_str] # one entry per smiles, lowest ppg used
            self.db = self.client[database]

        self.smarts_query_index = {}
        self._preloaded_pattern_cache: dict[str, dict[str, Any]] = {}
        self.count_collection = None
        self.config = config
        self.database = database
        self.collection_str = collection
        self.buyables_cache_dir = (
            buyables_cache_dir if buyables_cache_dir else db_config.BUYABLES_CACHE_DIR
        )
        self.preload_buyables = preload_buyables

        if self.preload_buyables:
            self._preload_buyables()

    @staticmethod
    def _buyables_dedup_match() -> dict:
        """Match filter for rows that participate in dedup / disk cache invalidation."""
        return {"mol": {"$ne": None}, "smiles": {"$ne": ""}}

    def _buyables_disk_paths(self, buyables_dir: str | None = None) -> dict[str, str]:
        root = buyables_dir or self.buyables_cache_dir
        return {
            "dir": root,
            "buyables": os.path.join(root, "buyables.jsonl.gz"),
            "features": os.path.join(root, "buyable_features.npy"),
            "pfpbits": os.path.join(root, "buyable_pfpbits.npy"),
            "meta": os.path.join(root, "buyables_cache_meta.json"),
        }

    def _read_buyables_cache_meta(self, meta_path: str) -> dict | None:
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _write_buyables_cache_meta(self, meta_path: str) -> None:
        meta = {
            "database": self.database,
            "collection": self.collection_str,
            "collection_document_count": self.collection.count_documents({}),
            "eligible_doc_count": self.collection.count_documents(
                self._buyables_dedup_match()
            ),
            "dedup_count": self.dedup_collection.count_documents({}),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def _buyables_preload_needs_rebuild(self, paths: dict[str, str]) -> bool:
        """
        Rebuild dedup + .npy/.jsonl.gz when Mongo changed vs last successful cache write.

        Tracks total doc count, eligible (mol+smiles) row count, and dedup size so we
        refresh when new buyables are added, precompute finishes, or dedup is stale.
        """
        logp = "[buyables preload]"
        print(f"{logp} cache dir: {paths['dir']}")
        print(f"{logp} meta path: {paths['meta']}")

        for key in ("buyables", "features", "pfpbits"):
            if not os.path.isfile(paths[key]):
                print(f"{logp} REBUILD: missing on-disk file ({key}) -> {paths[key]}")
                return True

        meta = self._read_buyables_cache_meta(paths["meta"])
        if meta is None:
            if os.path.isfile(paths["meta"]):
                print(
                    f"{logp} REBUILD: meta file exists but is invalid JSON -> {paths['meta']}"
                )
            else:
                print(f"{logp} REBUILD: no meta file -> {paths['meta']}")
            return True

        cur_total = self.collection.estimated_document_count()
        cur_eligible = self.collection.count_documents(self._buyables_dedup_match())
        cur_dedup = self.dedup_collection.estimated_document_count()

        meta_total = meta.get("collection_document_count")
        meta_eligible = meta.get("eligible_doc_count")
        meta_dedup = meta.get("dedup_count")
        meta_db = meta.get("database")
        meta_coll = meta.get("collection")

        print(
            f"{logp} Mongo now: database={self.database!r} collection={self.collection_str!r} "
            f"total_docs={cur_total} eligible_docs={cur_eligible} dedup_docs={cur_dedup}"
        )
        print(
            f"{logp} Meta file: database={meta_db!r} collection={meta_coll!r} "
            f"total_docs={meta_total} eligible_docs={meta_eligible} dedup_docs={meta_dedup}"
        )

        if meta_db != self.database or meta_coll != self.collection_str:
            print(
                f"{logp} REBUILD: database/collection in meta does not match "
                f"this Pricer (meta db/coll != current)"
            )
            return True
        if cur_total != meta_total:
            print(
                f"{logp} REBUILD: raw buyables collection doc count changed "
                f"(mongo {cur_total} != meta {meta_total})"
            )
            return True
        if cur_eligible != meta_eligible:
            print(
                f"{logp} REBUILD: eligible row count changed (mol+nonempty smiles) "
                f"(mongo {cur_eligible} != meta {meta_eligible})"
            )
            return True
        if cur_dedup != meta_dedup:
            print(
                f"{logp} REBUILD: buyables_to_preload doc count changed "
                f"(mongo {cur_dedup} != meta {meta_dedup})"
            )
            return True

        print(
            f"{logp} SKIP rebuild: on-disk cache matches Mongo counts; "
            f"loading {paths['buyables']}"
        )
        return False

    def add_dedup_collection(self):
        query = self._buyables_dedup_match()
        cursor = self.collection.aggregate(
            [
                {"$match": query},
                {"$sort": {"smiles": 1, "ppg": 1}},
                {
                    "$group": {
                        "_id": "$smiles",
                        "mol": {"$first": "$mol"},
                        "ppg": {"$first": "$ppg"},
                        "lead_time": {"$first": "$lead_time"},
                        "mfp": {"$first": "$mfp"},
                        "pfp": {"$first": "$pfp"},
                        "source": {"$addToSet": "$source"},
                        "ids": {"$addToSet": "$_id"},
                    }
                },
                {"$out": self.dedup_collection_str},
            ]
        )
        list(cursor)

    def _preload_buyables(self):
        """
        Load all buyables from the database into memory.

        Rebuilds ``buyables_to_preload`` and on-disk arrays when Mongo counts drift
        from ``buyables_cache_meta.json`` (new rows, new mols, or dedup out of sync).
        """
        paths = self._buyables_disk_paths()
        os.makedirs(paths["dir"], exist_ok=True)

        needs_rebuild = self._buyables_preload_needs_rebuild(paths)
        if needs_rebuild:
            print(
                "[buyables preload] Starting full rebuild of buyables_to_preload "
                "and feature files (see reason above)"
            )
            t0 = time.time()
            if not self.is_all_mols_precomputed(self.collection):
                print("Some mols not precomputed, running precompute_mols")
                self.precompute_mols()

            print("Refreshing buyables dedup collection (buyables_to_preload)")
            self.add_dedup_collection()

            print(
                f"{self.collection.count_documents(filter={})} docs in the buyables database"
            )
            print(
                f"{self.dedup_collection.count_documents(filter={})} docs in the dedup collection"
            )

            if not self.is_properties_precomputed():
                print("Adding precomputed properties")
                self.add_mol_properties()

            cursor = self.dedup_collection.find({}).sort(
                [("num_heavy_atoms", 1), ("len_smiles", 1), ("ppg", 1)]
            )
            self.num_buyables = self.dedup_collection.count_documents({})
            print(f"Loading {self.num_buyables} buyables into memory")

            self.buyables = []
            self.buyable_features = np.zeros(
                (self.num_buyables, 4 + len(ATOM_DICT)), dtype=float
            )
            self.buyable_pfpbits = np.zeros(
                (self.num_buyables, 2048), dtype=np.bool_
            )

            for i, doc in tqdm(enumerate(cursor), total=self.num_buyables):

                self.buyables.append(
                    {
                        "smiles": doc["_id"],
                        "mol": doc["mol"],
                        "source": doc["source"],
                    }
                )
                self.buyable_features[i][:4] = [
                    doc["ppg"],
                    doc["num_rings"],
                    doc["num_heavy_atoms"],
                    doc["pfp"]["count"],
                ]
                self.buyable_features[i][4:] = [
                    doc["atom_count"][atom] for atom in ATOM_DICT.keys()
                ]
                for bit in doc["pfp"]["bits"]:
                    self.buyable_pfpbits[i, bit] = True

            print(
                f"Loaded {len(self.buyables)} buyables in {time.time() - t0} seconds"
            )
            print("Saving buyables to disk")
            np.save(paths["features"], self.buyable_features)
            self.buyable_pfpbits = np.packbits(self.buyable_pfpbits, axis=1)
            del self.buyable_pfpbits
            np.save(paths["pfpbits"], self.buyable_pfpbits)
            with gzip.open(paths["buyables"], "wt") as f:
                for buyable in self.buyables:
                    f.write(json_util.dumps(buyable) + "\n")
            self._write_buyables_cache_meta(paths["meta"])
            print("Saved files for buyables preloading.")

        with gzip.open(paths["buyables"], "r") as f:
            self.buyables = [json_util.loads(line) for line in f.readlines()]
        self.num_buyables = len(self.buyables)

        for doc in tqdm(self.buyables, desc="Converting Binary to Mol objects"):
            doc["mol"] = Chem.Mol(doc["mol"])

        self.buyable_features = np.load(paths["features"])
        self.buyable_pfpbits = np.load(paths["pfpbits"])
        self.max_ppg = np.max(self.buyable_features[:, 0])
        print(f"[pricer] Setup complete: {self.num_buyables} buyables ready in memory")


    @staticmethod
    def _source_to_query(source: list[str] | str | None) -> list[str] | None:
        """
        Convert no source keyword to query for MongoDB.

        Args:
            source (str or list): source names, possibly including 'none'

        Returns:
            list: modified source list replacing 'none' with None and ''
        """
        if source is not None:
            if not isinstance(source, list):
                source = [source]
            if "none" in source:
                # Include both null and empty string source in query
                source.remove("none")
                source.extend([None, ""])

        return source

    def lookup_smiles(
        self,
        smiles: str,
        source: list[str] | str | None = None
    ) -> dict | None:
        if source == []:
            # If no sources are allowed, there is no need to perform lookup
            # Empty list is checked explicitly here, since None means source
            # will not be included in query, and '' is a valid source value
            return None

        if self.collection is not None:
            query = {"smiles": smiles}

            if source is not None:
                query["source"] = {"$in": self._source_to_query(source)}

            cursor = self.collection.find(query)
            result = min(cursor, key=lambda x: x["ppg"], default=None)
            if result:
                result["_id"] = str(result["_id"])
                # keeping only these fields. Once the mols are computed, serialization
                # becomes an issue.
                result = {
                    k: v for k, v in result.items() if k in [
                        "_id", "smiles", "ppg", "lead_time", "source", "properties"
                    ]
                }
            return result
        else:
            return None

    def lookup_smiles_list(
        self,
        smiles_list: list[str],
        source: list[str] | str | None = None
    ) -> dict[str, Any]:
        query = {"smiles": {"$in": smiles_list}}

        if source is not None:
            query["source"] = {"$in": self._source_to_query(source)}

        cursor = self.collection.aggregate(
            [
                {"$match": query},
                {"$sort": {"smiles": 1, "ppg": 1}},
                {
                    "$group": {
                        "_id": "$smiles",
                        "ppg": {"$first": "$ppg"},
                        "source": {"$first": "$source"},
                    }
                },
            ]
        )
        result = {}
        for doc in cursor:
            result[str(doc.pop("_id"))] = {
                k: v for k, v in doc.items()
                if k in ["smiles", "ppg", "lead_time", "source", "properties"]
            }

        return result

    def is_mols_precomputed(self) -> bool:
        query = {"mol": {"$ne": None}, "smiles": {"$ne": ''}}
        result = self.collection.find_one(query)
        if result:
            return True
        else:
            return False

    def is_all_mols_precomputed(self, collection) -> bool:
        query = {"mol": {"$eq": None}, "smiles": {"$ne": ''}}
        result = collection.find_one(query)
        if result:
            return False
        else:
            return True

    def is_properties_precomputed(self) -> bool:
        query = {"len_smiles": {"$exists": False}}
        result = self.dedup_collection.find_one(query)
        if result:
            return False
        else:
            return True

    def precompute_mols(self, batch_size: int = 10000) -> None:
        """
        Stores rdkit Mol objects as a Binary,a molecular fingerprint and bit
        counts, and a pattern fingerprint and bit counts for each molecule in
        the database
        """
        print(f"{self.collection.count_documents(filter={})} "
              f"documents in the buyables database")
        idxs = [s["_id"] for s in self.collection.find({}, {"_id": 1}) if s]
        full_batch_idx = int(len(idxs) / batch_size) * batch_size
        if batch_size > len(idxs):
            batched_idxs = [idxs]
        else:
            splits = list(range(0, full_batch_idx, batch_size)) + [len(idxs)]
            batched_idxs = [idxs[i:j] for i, j in zip(splits[:-1], splits[1:])]

        document_list = []
        print(f"Precomputing mols in {len(batched_idxs)} batches")
        mfp_counts = {}
        for i, batch in enumerate(batched_idxs):
            query = {"_id": {"$in": batch}}
            documents = self.collection.find(query)
            for document in documents:
                rdmol = Chem.MolFromSmiles(document["smiles"])
                mfp = list(
                    AllChem.GetMorganFingerprintAsBitVect(
                        rdmol, 2, nBits=2048
                    ).GetOnBits()
                )
                pfp = list(Chem.rdmolops.PatternFingerprint(rdmol).GetOnBits())
                document["mol"] = Binary(rdmol.ToBinary())
                document["mfp"] = {"bits": mfp, "count": len(mfp)}
                document["pfp"] = {"bits": pfp, "count": len(pfp)}
                document_list.append(document)

                for bit in mfp:
                    mfp_counts[bit] = mfp_counts.get(bit, 0) + 1
            self.collection.delete_many(query)

            print(f"Done computing RDK mol objects for batch "
                  f"{i} out of {len(batched_idxs)}")
            self.collection.insert_many(document_list)
            document_list = []

        print(f"{self.collection.count_documents(filter={})} "
              f"documents in the buyables database")

        self.count_collection = self.db["count_collection"]
        self.count_collection.delete_many({})
        print(f"{self.count_collection.count_documents(filter={})} "
              f"documents in the counts database")
        for k, v in mfp_counts.items():
            self.count_collection.insert_one({"_id": k, "count": v})
        self.collection.create_index("mfp.bits")
        self.collection.create_index("mfp.count")
        self.collection.create_index("pfp.bits")
        self.collection.create_index("pfp.count")

        print("Created new indexes in the database")
        self.buyables = list(self.collection.find({}))
        print("Updated buyables list")

    def add_mol_properties(self) -> None:
        """
        Adds moleculer properties to the database
        1) Number of heavy atoms
        2) Number of rings
        3) Atom count
        4) Length of smiles
        """

        print("Running add_mol_properties")

        cursor = self.dedup_collection.find(
            {"len_smiles": {"$exists": False}}
        )
        for doc in tqdm(cursor):
            rdmol = Chem.Mol(doc["mol"])
            atom_count = {}

            for sym, num in ATOM_DICT.items():

                atom_count[sym] = len(
                    rdmol.GetAtomsMatchingQuery(
                        rdqueries.AtomNumEqualsQueryAtom(num)
                    ))
 
            self.dedup_collection.update_one(
                doc, 
                {'$set': {
                    'num_heavy_atoms': rdmol.GetNumHeavyAtoms(), 
                    'num_rings':rdMolDescriptors.CalcNumRings(rdmol),  
                    'atom_count': atom_count,
                    'len_smiles': len(str(doc["_id"]))
                }})    

        for sym in ATOM_DICT.keys():
            self.dedup_collection.create_index(f"atom_count.{sym}")
        self.dedup_collection.create_index("num_heavy_atoms")
        self.dedup_collection.create_index("num_rings")
        self.dedup_collection.create_index("len_smiles")

    def lookup_smarts(
        self,
        smarts: str,
        limit: int | None = None,
        precomputed_mols: bool = False,
        version: str = 'default',
        max_ppg: float | None = None,
        #source: Annotated[list[str] | None, Query()] = None,
        convert_smiles: bool = False,
        
    ) -> dict | None:
        
        
        if version.startswith("preloaded"):
            return self._lookup_smarts_preloaded(
                smarts=smarts,
                limit=limit,
                max_ppg=max_ppg,
                convert_smiles=convert_smiles
                #source=source
            )
        
        else:
            return self._lookup_smarts(
                smarts=smarts,
                limit=limit,
                max_ppg=max_ppg,
                precomputed_mols=precomputed_mols
            )
        
    def _preloaded_prefilter(self, pattern, max_ppg: float):
        """Vectorized prefilter for a SMARTS pattern against preloaded buyables."""
        query_fp = Chem.rdmolops.PatternFingerprint(pattern).GetOnBits()

        query = np.zeros(4 + len(ATOM_DICT), dtype=float)
        query[0] = max_ppg
        try:
            q2 = Chem.Mol(pattern)
            q2.UpdatePropertyCache()
            Chem.GetSymmSSSR(q2)
            numRings = rdMolDescriptors.CalcNumRings(q2)
            if numRings:
                query[1] = numRings
        except Exception as e:
            print(f"Error in ring count: {e}")
        query[2] = pattern.GetNumHeavyAtoms()
        query[3] = len(query_fp)
        for i, sym in enumerate(ATOM_DICT.keys()):
            q = rdqueries.AtomNumEqualsQueryAtom(ATOM_DICT[sym])
            query[4 + i] = len(pattern.GetAtomsMatchingQuery(q))

        # Skip molecules lighter than the query (col 2 = num_heavy_atoms, sorted asc at load)
        start = int(np.searchsorted(self.buyable_features[:, 2], query[2]))
        sub_feat = self.buyable_features[start:]
        sub_bits = self.buyable_pfpbits[start:]

        feature_passed = np.where(
            np.all(sub_feat[:, 1:len(query)] >= query[1:len(query)], axis=1)
            & (sub_feat[:, 0] <= query[0])
        )[0]

        if not len(feature_passed):
            return np.empty(0, dtype=np.intp)

        qbool = np.zeros(2048, dtype=bool)
        qbool[list(query_fp)] = True
        qpacked = np.packbits(qbool)
        cand = sub_bits[feature_passed]
        bits_ok = np.all((cand & qpacked) == qpacked, axis=1)
        return feature_passed[bits_ok] + start

    def _preloaded_matches_for_pattern(
        self,
        pattern_smarts: str,
        limit: int | None,
        max_ppg: float,
    ) -> list[dict[str, Any]]:
        """
        Cached substructure hits for one pattern, independent of ``max_ppg``.

        ``HasSubstructMatch`` does not depend on price, so the cache key is the
        pattern alone. ``max_ppg`` only controls the prefilter (which candidates
        are considered) and a final ppg filter on results. Because
        ``filtered_indices(M) ⊆ filtered_indices(M')`` when ``M <= M'`` (ppg
        only gets more permissive; other prefilter features are ppg-independent),
        a previous exhaustive scan at ``M'`` covers every lower ``M``.
        """
        max_ppg = float(max_ppg)
        entry = self._preloaded_pattern_cache.get(pattern_smarts)
        if entry is None:
            entry = {
                "tested": set(),
                "matched_order": [],
                "matched_set": set(),
                "exhaustive_upto_ppg": float("-inf"),
            }
            self._preloaded_pattern_cache[pattern_smarts] = entry

        def _make_result(idx: int) -> dict[str, Any]:
            return {
                "smiles": self.buyables[idx]["smiles"],
                "source": self.buyables[idx]["source"],
                "ppg": float(self.buyable_features[idx][0]),
            }

        # Fast path: a previous exhaustive scan already covers this max_ppg.
        if max_ppg <= entry["exhaustive_upto_ppg"]:
            results: list[dict[str, Any]] = []
            for idx in entry["matched_order"]:
                if float(self.buyable_features[idx][0]) > max_ppg:
                    continue
                results.append(_make_result(idx))
                if limit is not None and len(results) >= limit:
                    return results

            return results

        # Slow path: walk the prefilter at this max_ppg, consulting the cache
        # to avoid re-running HasSubstructMatch for indices we've seen before.
        pattern = Chem.MolFromSmarts(pattern_smarts)
        filtered_indices = self._preloaded_prefilter(pattern, max_ppg)
        total = int(len(filtered_indices))

        results = []
        stopped_early = False
        start = time.time()
        n_new_tests = 0
        for pos in range(total):
            if pos % 1000 == 0 and pos > 0:
                print(
                    f"substructure match (cnt={pos}/{total})",
                    time.time() - start,
                    "seconds",
                )
            idx = int(filtered_indices[pos])
            if idx in entry["matched_set"]:
                results.append(_make_result(idx))
            elif idx in entry["tested"]:
                continue
            else:
                entry["tested"].add(idx)
                n_new_tests += 1
                if self.buyables[idx]["mol"].HasSubstructMatch(
                    pattern, useChirality=True
                ):
                    entry["matched_set"].add(idx)
                    entry["matched_order"].append(idx)
                    results.append(_make_result(idx))
            if limit is not None and len(results) >= limit:
                stopped_early = True
                break

        if not stopped_early and max_ppg > entry["exhaustive_upto_ppg"]:
            entry["exhaustive_upto_ppg"] = max_ppg

        return results

    def _lookup_smarts_preloaded(
        self,
        smarts: str,
        limit: int | None = None,
        max_ppg: float | None = None,
        convert_smiles: bool = True,
    ) -> list[dict[str, Any]]:
        # print("Running preloaded (vectorized) buyables search for:", smarts)
        api_start = time.time()

        eff_max_ppg = float(max_ppg) if max_ppg else float(self.max_ppg)

        if convert_smiles:
            smarts_list = self.abs_smiles_to_smarts_query(smarts)
        else:
            smarts_list = [smarts]

        buyables_list: list[dict[str, Any]] = []
        for pattern_smarts in smarts_list:
            remaining = None if limit is None else limit - len(buyables_list)
            if remaining is not None and remaining <= 0:
                break
            buyables_list.extend(
                self._preloaded_matches_for_pattern(
                    pattern_smarts=pattern_smarts,
                    limit=remaining,
                    max_ppg=eff_max_ppg,
                )
            )

        # print("Total api call time:", time.time() - api_start, "seconds")
        return buyables_list if limit is None else buyables_list[:limit]
    def _lookup_smarts(
        self,
        smarts: str,
        limit: int | None = None,
        max_ppg: float | None = None,
        precomputed_mols: bool = False
    ) -> list:
        """
        Lookup molecules in the database using a SMARTS pattern string

        Note: assumes that a Mol Object and pattern fingerprints are stored for
            each SMILES entry in the database

        Returns:
            A dictionary with one database entry for each molecule match

        Note:
            Implementation adapted from https://github.com/rdkit/mongo-rdkit/blob
                /master/mongordkit/Search/substructure.py
        """
        if not self.is_mols_precomputed():
            self.precompute_mols()

        if smarts in self.smarts_query_index.keys():
            matched_ids = self.smarts_query_index[smarts]
            query = {"smiles": {"$in": matched_ids}}
            cursor = self.collection.aggregate(
                [
                    {"$match": query},
                    {"$sort": {"ppg": 1}},
                    {
                        "$group": {
                            "_id": "$smiles",
                            "smiles": {"$first": "$smiles"},
                            "ppg": {"$first": "$ppg"},
                            "source": {"$first": "$source"}
                        }
                    }
                ]
            )
            # result = list(result)
            result = []
            for doc in cursor:
                trimmed_doc = {
                    "_id": str(doc["_id"]),
                    "smiles": doc["smiles"],
                    "ppg": doc["ppg"],
                    "source": doc["source"]
                }
                result.append(trimmed_doc)

        else:
            pattern = Chem.MolFromSmarts(smarts)
            query_fp = list(Chem.rdmolops.PatternFingerprint(pattern).GetOnBits())
            qfp_len = len(query_fp)
            matched_ids = []
            query = {
                "mol": {"$ne": None},
                "pfp.count": {"$gte": qfp_len},
                "pfp.bits": {"$all": query_fp},
            }

            if max_ppg:
                query["ppg"] = {"$lte": max_ppg}

            cursor = self.collection.aggregate(
                [
                    {"$match": query},
                    {
                        "$group": {
                            "_id": "$_id",
                            "smiles": {"$first": "$smiles"},
                            "mol": {"$first": "$mol"},
                            "ppg": {"$first": "$ppg"},
                            "source": {"$first": "$source"}
                        }
                    }
                ]
            )

            # Perform substructure matching
            result = []
            for i, doc in enumerate(cursor):
                try:
                    rdmol = Chem.Mol(doc["mol"])
                    if rdmol.HasSubstructMatch(pattern, useChirality=True):
                        matched_ids.append(doc["_id"])
                        # Not returning the "mol"; serialization issue with fastapi
                        trimmed_doc = {
                            "_id": str(doc["_id"]),
                            "smiles": doc["smiles"],
                            "ppg": doc["ppg"],
                            "source": doc["source"]
                        }
                        result.append(trimmed_doc)
                except KeyError as e:
                    print("Key error {}, {}".format(e, doc["smiles"]))

            self.smarts_query_index[smarts] = matched_ids

        if limit:
            result = result[:limit]

        return result

    def lookup_similar_smiles(
        self,
        smiles: str,
        sim_threshold: float,
        limit: int = None,
        method: str = "accurate"
    ) -> list:
        """
        Lookup molecules in the database based on tanimoto similarity to the input
        SMILES string

        Note: assumes that a Mol Object, and Morgan Fingerprints are stored for
            each SMILES entry in the database

        Returns:
            A dictionary with one database entry for each molecule match including
            the tanimoto similarity to the query

        Note:
            Currently there are two options implemented lookup methods.
            The 'accurate' method is based on an aggregation pipeline in Mongo.
            The 'fast' method uses locality-sensitive hashing to greatly improve
            the lookup speed, at the cost of accuracy (especially at lower
            similarity thresholds).
        """
        if not self.is_mols_precomputed():
            self.precompute_mols()

        query_mol = Chem.MolFromSmiles(smiles)
        if method == "accurate":
            results = sim_search_aggregate_buyables(
                query_mol,
                self.collection,
                None,
                sim_threshold,
            )
        elif method == "naive":
            results = sim_search_buyables(
                query_mol,
                self.collection,
                None,
                sim_threshold,
            )
        elif method == "fast":
            raise NotImplementedError
        else:
            raise ValueError(f"Similarity search method '{method}' not implemented")

        results = sorted(results, key=lambda x: x["tanimoto"], reverse=True)
        if limit:
            results = results[:limit]

        return results
    
    def abs_smiles_to_smarts_query(self, smiles: str) -> list[str]:
        
        return abs_smiles_to_smarts_query(smiles=smiles)

class FilePricer:
    def __init__(self, path: str, precompute_mols: bool = False):
        """
        Load price data from local file.
        """
        if os.path.isfile(path):
            self.path = path
            self.data = pd.read_json(
                path,
                orient="records",
                dtype={"smiles": "object", "source": "object", "ppg": "float"},
                compression="gzip",
            )
            print(f"Loaded prices from flat file: {path}")
            self.indexed_queries = {}
        else:
            print(f"Buyables file does not exist: {path}")

        if precompute_mols:
            self.data["mols"] = [Chem.MolFromSmiles(x) for x in self.data["smiles"]]

        self.smarts_query_index = {}

    def lookup_smiles(
        self,
        smiles: str,
        source: list[str] | str | None = None
    ) -> dict | None:
        if source == []:
            # If no sources are allowed, there is no need to perform lookup
            # Empty list is checked explicitly here, since None means source
            # will not be included in query, and '' is a valid source value
            return None

        if self.data is not None:
            query = self.data["smiles"] == smiles

            if source is not None:
                if isinstance(source, list):
                    query = query & (self.data["source"].isin(source))
                else:
                    query = query & (self.data["source"] == source)

            results = self.data.loc[query]
            if len(results.index):
                idxmin = results["ppg"].idxmin()
                return results.loc[idxmin].to_dict()
            else:
                return None
        else:
            return None

    def lookup_smiles_list(
        self,
        smiles_list: list[str],
        source: list[str] | str | None = None
    ):
        raise NotImplementedError

    def lookup_smarts(
        self,
        smarts: str,
        limit: int | None = None,
        precomputed_mols: bool = False, 
        version: str = 'default',
        max_ppg: float | None = None,
        convert_smiles: bool = False, # convert abstracted smiles to smarts for matching with buyables 
    ) -> dict:

        if smarts not in self.smarts_query_index.keys() \
            or self.smarts_query_index[smarts] < limit:
            if precomputed_mols:
                pattern = Chem.MolFromSmarts(smarts)
                matches = self.data["mols"].apply(lambda x: x.HasSubstructMatch(pattern))
                self.smarts_query_index[smarts] = matches

            else:
                pattern = Chem.MolFromSmarts(smarts)
                matches = self.data["smiles"].apply(
                    lambda x: Chem.MolFromSmiles(x).HasSubstructMatch(pattern)
                )
                self.smarts_query_index[smarts] = matches

        matches = self.smarts_query_index[smarts]
        return self.data[matches].to_dict(orient="records")

    def abs_smiles_to_smarts_query(self, smiles: str) -> list[str]:
        return abs_smiles_to_smarts_query(smiles=smiles)