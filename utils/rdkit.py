import json
import traceback as tb
from fastapi import Response
from pydantic import BaseModel
from rdchiral.initialization import rdchiralReactants, rdchiralReaction
from rdchiral.main import rdchiralRun
from rdkit import Chem
from rdkit.Chem import Descriptors, rdDepictor, SDWriter, AllChem
from typing import Any
from utils import register_util
from utils.draw_impl import align_molecule
from utils.registry import get_util_registry
from io import StringIO


class SmilesInput(BaseModel):
    smiles: str
    isomericSmiles: bool = True
    reference: str = None


class MolfileInput(BaseModel):
    molfile: str
    isomericSmiles: bool = True


class RDKitAsyncReturn(BaseModel):
    request: dict
    task_id: str


def molecular_weight(smiles: str) -> float:
    """
    Calculate exact molecular weight for the given SMILES string

    Args:
        smiles: SMILES string for which to calculate molecular weight

    Returns:
         float: exact molecular weight
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        molwt = Descriptors.ExactMolWt(mol)

        return molwt
    except Exception:
        mol = Chem.MolFromSmiles(smiles, sanitize=False)
        if mol is None:
            return 9999.0
        mol.UpdatePropertyCache(strict=False)
        molwt = Descriptors.ExactMolWt(mol)

        return molwt


def _canonicalize(_smi: str, isomericSmiles: bool) -> str:
    if _smi:
        _mol = Chem.MolFromSmiles(_smi)
        if not _mol:
            raise ValueError("Cannot parse smiles with rdkit.")
        _smi = Chem.MolToSmiles(_mol, isomericSmiles=isomericSmiles)
        if not _smi:
            raise ValueError("Cannot canonicalize smiles with rdkit.")
    return _smi

def get_core_fragment(smiles):
    """
    Extract the core fragment from a molecule for identifying near cycles in IPP (Inverse Planning Problem).
    
    The core fragment is defined as the union of:
        - All atoms that have atom mapping numbers (mapped atoms)
        - All carbon atoms that are directly connected to mapped carbon atoms
        - All ring atoms that are part of any ring containing the above atoms
    
    Non-core atoms are processed as follows:
        - Atoms connected to core atoms are replaced with dummy atoms (atomic number 0)
        - Completely disconnected atoms are removed from the molecule

    
    Args:
        smiles (str): SMILES string of the molecule to extract core fragment from.

    
    Returns:
        tuple: A tuple containing:
            - str: SMILES string of the core fragment with dummy atoms for peripheral groups,
                  or None if the input SMILES cannot be parsed
            - str: Canonical SMILES of the original molecule with all atom mappings removed,
                  or None if the input SMILES cannot be parsed
    """

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None, None

    mol = Chem.RWMol(mol)

    mapped = {atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomMapNum() > 0}

    
    keep_atoms = set(mapped)
    [x.SetAtomMapNum(0) for x in mol.GetAtoms()]
    
    canon_smiles = Chem.MolToSmiles(mol, isomericSmiles=True)

    # Add ring atoms that are in rings with any current kept atoms
    ring_info = mol.GetRingInfo()
    for ring in ring_info.AtomRings():
        if any(idx in keep_atoms for idx in ring):
            keep_atoms.update(ring)

    # Determine which atoms to replace with dummies or delete
    to_replace = set()
    to_delete = set()
    for atom in mol.GetAtoms():
        idx = atom.GetIdx()
        if idx in keep_atoms:
            continue
        neighbor_idxs = [nbr.GetIdx() for nbr in atom.GetNeighbors()]
        if any(n in keep_atoms for n in neighbor_idxs):
            to_replace.add(idx)
        else:
            to_delete.add(idx)

    # Replace atoms with dummies
    for idx in to_replace:
        atom = mol.GetAtomWithIdx(idx)
        atom.SetAtomicNum(0)
        atom.SetIsAromatic(False)
        atom.SetFormalCharge(0)
        atom.SetNoImplicit(True)
        atom.SetAtomMapNum(0)

    # Remove unconnected atoms
    for idx in sorted(to_delete, reverse=True):
        mol.RemoveAtom(idx)

    Chem.SanitizeMol(mol)

    # return larger fragment only
    frags = Chem.GetMolFrags(mol, asMols=True)
    largest_frag = max(frags, key=lambda m: m.GetNumAtoms())

    return Chem.MolToSmiles(largest_frag), canon_smiles


@register_util(name="rdkit")
class RDKitUtil:
    """Util class for RDKit"""
    prefixes = ["rdkit"]
    methods_to_bind: dict[str, list[str]] = {
        "canonicalize": ["POST"],
        "validate": ["POST"],
        "from_molfile": ["POST"],
        "to_molfile": ["POST"],
        "to_sdfile": ["POST"],
        "apply_one_template": ["POST"],
        "apply_one_template_by_idx": ["POST"],
        "get_core_fragment": ["POST"],
    }

    def __init__(self, util_config: dict[str, Any] = None):
        pass

    @staticmethod
    def canonicalize(input: SmilesInput) -> Response:
        smiles = input.smiles
        isomericSmiles = input.isomericSmiles

        resp = {}
        try:
            if ">" in smiles:
                resp["type"] = "rxn"
                resp["smiles"] = ">".join(
                    _canonicalize(part, isomericSmiles) for part in smiles.split(">")
                )
            else:
                resp["type"] = "mol"
                resp["smiles"] = _canonicalize(smiles, isomericSmiles)
        except ValueError:
            resp["error"] = f"Unable to canonicalize using RDKit, traceback: " \
                            f"{tb.format_exc()}"
            return Response(
                content=json.dumps(resp),
                status_code=500,
                media_type="application/json"
            )
        else:
            return Response(
                content=json.dumps(resp),
                status_code=200,
                media_type="application/json"
            )
    
    @staticmethod
    def get_core_fragment(input: SmilesInput) -> Response:
        smiles = input.smiles

        resp = {}
        try:
            core_fragment, canon_smiles = get_core_fragment(smiles)
            resp["core_fragment"] = core_fragment
            resp["canon_smiles"] = canon_smiles
        except Exception:
            resp["error"] = f"Unable to get core fragment using RDKit, traceback: " \
                            f"{tb.format_exc()}"
            return Response(
                content=json.dumps(resp),
                status_code=500,
                media_type="application/json"
            )
        else:
            return Response(
                content=json.dumps(resp),
                status_code=200,
                media_type="application/json"
            )

    @staticmethod
    def validate(input: SmilesInput) -> Response:
        smiles = input.smiles

        mol = Chem.MolFromSmiles(smiles, sanitize=False)

        if mol is None:
            correct_syntax = False
            valid_chem_name = False
        else:
            correct_syntax = True
            try:
                Chem.SanitizeMol(mol)
            except Exception:
                valid_chem_name = False
            else:
                valid_chem_name = True

        resp = {
            "correct_syntax": correct_syntax,
            "valid_chem_name": valid_chem_name,
        }

        return Response(
            content=json.dumps(resp),
            status_code=200,
            media_type="application/json"
        )

    @staticmethod
    def from_molfile(input: MolfileInput):
        """
        Convert the provided Molfile to a SMILES string.

        Method: POST

        Parameters:

        - `molfile` (str): Molfile input
        - `isomericSmiles` (bool, optional): whether to generate isomeric SMILES

        Returns:

        - `smiles` (str): canonical SMILES
        """
        molfile = input.molfile
        isomericSmiles = input.isomericSmiles

        resp = {}

        mol = Chem.MolFromMolBlock(molfile)
        if not mol:
            resp["error"] = "Cannot parse sdf molfile with rdkit."

            return Response(
                content=json.dumps(resp),
                status_code=500,
                media_type="application/json"
            )

        try:
            smiles = Chem.MolToSmiles(mol, isomericSmiles=isomericSmiles)
        except Exception:
            resp["error"] = "Cannot parse sdf molfile with rdkit."

            return Response(
                content=json.dumps(resp),
                status_code=500,
                media_type="application/json"
            )

        resp["smiles"] = smiles

        return Response(
            content=json.dumps(resp),
            status_code=200,
            media_type="application/json"
        )

    @staticmethod
    def to_molfile(input: SmilesInput):
        """
        Convert the provided SMILES string to a Molfile.

        Method: POST

        Parameters:

        - `smiles` (str): SMILES input
        - `reference` (str, optional): SMILES of reference molecule for alignment

        Returns:

        - `molfile` (str): Molfile output
        """

        smiles = input.smiles
        reference = input.reference

        resp = {}

        mol = Chem.MolFromSmiles(smiles)
        if not mol:
            resp["error"] = "Cannot parse smiles with rdkit."

            return Response(
                content=json.dumps(resp),
                status_code=500,
                media_type="application/json"
            )

        if reference:
            ref = Chem.MolFromSmiles(reference)
            align_molecule(mol, ref)
        else:
            rdDepictor.Compute2DCoords(mol)

        try:
            molfile = Chem.MolToMolBlock(mol)
        except Exception:
            resp["error"] = "Cannot parse smiles with rdkit."

            return Response(
                content=json.dumps(resp),
                status_code=500,
                media_type="application/json"
            )

        resp["molfile"] = molfile

        return Response(
            content=json.dumps(resp),
            status_code=200,
            media_type="application/json"
        )

    @staticmethod
    def apply_one_template(smiles: str, reaction_smarts: str) -> list[str]:
        reaction_smarts_one = "(" + reaction_smarts.replace(">>", ")>>(") + ")"
        rxn = rdchiralReaction(str(reaction_smarts_one))
        prod = rdchiralReactants(smiles)

        try:
            reactants = rdchiralRun(rxn, prod, return_mapped=False)
        except:
            return []

        if not reactants:
            return []

        return reactants

    def apply_one_template_by_idx_sync(
        self,
        smiles: str,
        template_idx: int,
        template_set: str
    ) -> list[str]:
        template_controller = get_util_registry().get_util(module="template")
        reaction_smarts = template_controller.find_one_by_idx(
            template_idx=template_idx,
            template_set=template_set
        )["reaction_smarts"]

        try:
            return self.apply_one_template(
                smiles=smiles,
                reaction_smarts=reaction_smarts
            )
        except:
            return []

    @staticmethod
    async def apply_one_template_by_idx(
        smiles: str,
        template_idx: int,
        template_set: str,
        priority: int = 0
    ) -> RDKitAsyncReturn:
        from askcos2_celery.tasks import rdkit_apply_one_template_by_idx_task

        async_result = rdkit_apply_one_template_by_idx_task.apply_async(
            args=(smiles, template_idx, template_set), priority=priority)
        task_id = async_result.id

        request = {
            "smiles": smiles,
            "template_idx": template_idx,
            "template_set": template_set
        }
        async_return = RDKitAsyncReturn(
            request=request,
            task_id=task_id
        )

        return async_return
    
    @staticmethod
    async def to_sdfile(smiles: str)-> Response:
        resp = {}
        mol = Chem.MolFromSmiles(smiles)
        if not mol:
            resp["error"] = "Cannot parse smiles with rdkit."

            return Response(
                content=json.dumps(resp),
                status_code=500,
                media_type="application/json"
            )
        
        mol_with_hs = Chem.AddHs(mol)

        AllChem.EmbedMolecule(mol_with_hs)
        AllChem.UFFOptimizeMolecule(mol_with_hs)
    
        sdf_buffer = StringIO()
        writer = SDWriter(sdf_buffer)
        writer.write(mol_with_hs)
        writer.close()
    
        sdf_content = sdf_buffer.getvalue()
        sdf_buffer.close()

        resp["sdf"] = sdf_content

        return Response(
            content=json.dumps(resp),
            status_code=200,
            media_type="application/json"
        )
        


