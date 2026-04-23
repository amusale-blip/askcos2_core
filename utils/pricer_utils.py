"""Utility functions for handling abstracted groups in Pricer."""

from rdkit import Chem
from rdkit.Chem import AllChem
from utils.electronegs import MORE_ELECTRONEG, LESS_ELECTRONEG, NON_CH

ATOM_DICT = {"C": 6, "N": 7, "O": 8, "F":9, "P": 15, "S":16, "Cl": 17, "Br":35}

def get_smarts_for_atom(mol, idx, isotope):
    
    smarts_token = get_frag_around_atom(mol, idx)
    if isotope == 5: # C-
        return (
            # potential structure matches
            smarts_token.replace('[5#6]', f';$([#6](~{LESS_ELECTRONEG})')+ ')' 
            # exclude C~C
            + ';!$(' + smarts_token.replace('[5#6]', f'[#6](~[#6])') + ')'
        )
        
        
    elif isotope == 4: # C+
        return (
            # potential structure matches
            smarts_token.replace('[4#6]', f';$([#6](~{MORE_ELECTRONEG})')+ ')' 
            # exclude following structures (C~C or C~LESS_ELECTRONEG)
            + ';!$(' + smarts_token.replace('[4#6]', f'[#6](~{LESS_ELECTRONEG.replace("[", "[#6,")})') + ')'
        )
    
    elif isotope == 3: # triple bond
        return (
            smarts_token.replace('[3#6]', f'&$([#6](#;!@[#6])')+ ')'
            + ';!$(' + smarts_token.replace('[3#6]', f'[#6](-,=[#6])')+ ')'
            + ';!$(' + smarts_token.replace('[3#6]', f'[#6](~{NON_CH})') + ')'
        )

    else: # isotope == 2 # double bond
        return (
            smarts_token.replace('[2#6]', f'&$([#6](=;!:;!@[#6])')+ ')'
            + ';!$(' + smarts_token.replace('[2#6]', f'[#6](-,#[#6])')+ ')'
            + ';!$(' + smarts_token.replace('[2#6]', f'[#6](~{NON_CH})') + ')'
        )

change_rxns = [
    AllChem.ReactionFromSmarts('[C;1*:1]=[1O:2]>>[0C:1]=[0O:2]'),
    AllChem.ReactionFromSmarts('[C;4*,5*:1]=[1O:2]>>[C:1](-[Xe]-[At])(-[Xe]-[At])'),
    AllChem.ReactionFromSmarts('[C;4*,5*:1]=[1O:2]>>[C:1]1(-[Xe]-[At]-[Xe]1)'),
    AllChem.ReactionFromSmarts('[C;1*:1]=[1O:2]>>[0C:1](-[Xe]-[At])(-[Xe]-[At])'),
    AllChem.ReactionFromSmarts('[C;1*:1]=[1O:2]>>[0C:1]1(-[Xe]-[At]-[Xe]1)'),
]

def get_atom_symbol(atom):

    symbol = '[#{}'.format(atom.GetAtomicNum())
    
    if not atom.GetIsotope() and atom.GetAtomicNum() not in [54, 85]:
        symbol += ';a' if atom.GetIsAromatic() else ';A'
        symbol += ';H{}'.format(atom.GetTotalNumHs())
        symbol += f';+{atom.GetFormalCharge()}' if atom.GetFormalCharge()>=0 \
            else f';{atom.GetFormalCharge()}'

    return symbol + ']'


def get_frag_around_atom(mol, idx):
    '''Builds a MolFragment using neighbors of an atom
    Adapted from https://github.com/connorcoley/rdchiral/blob/master/rdchiral/template_extractor.py
    '''
    ids_to_include = [idx]
    for neighbor in mol.GetAtomWithIdx(idx).GetNeighbors():
        ids_to_include.append(neighbor.GetIdx())
        for neighbor2 in neighbor.GetNeighbors():
            if neighbor2.GetIdx() not in ids_to_include:
                ids_to_include.append(neighbor2.GetIdx())


    # keep isotope labels for the atom of interest
    symbols = ['[{}#{}]'.format(a.GetIsotope(), a.GetAtomicNum()) if a.GetIdx() == idx\
               else get_atom_symbol(a) for a in mol.GetAtoms()]

    return Chem.MolFragmentToSmiles(mol, ids_to_include, isomericSmiles=True,
                                   atomSymbols=symbols, allBondsExplicit=True,
                                   allHsExplicit=True, rootedAtAtom=idx)

def change_carbonyl_group(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return [smiles]
    all_changed_smiles = [smiles]
    for change_rxn in change_rxns:
        for prod_tuple in change_rxn.RunReactants((mol,)):
            try:
                product = prod_tuple[0]
                Chem.SanitizeMol(product)
                outcome = Chem.MolToSmiles(product, isomericSmiles=True)
                all_changed_smiles.extend(change_carbonyl_group(outcome))
            except Exception:
                continue
    return all_changed_smiles

def abs_smiles_to_smarts_query(smiles: str) -> list[str]:
    """
    Converts (abstracted) smiles to smarts for lookup_smarts
    For higher-level retrosynthesis
    """
    smarts_list = []

    for smi in set(change_carbonyl_group(smiles)):

    # converting abstracted smiles to smarts for matching with buyables 
        mol = Chem.MolFromSmiles(smi)
        [x.SetAtomMapNum(i+1) for i, x in enumerate(mol.GetAtoms())]
        mol_copy = Chem.Mol(mol)
        replace_dict = {}
        #print(smi)

        # add explicit Hs for atoms without isotope labels
        for i, a in enumerate(mol.GetAtoms()): 

            if a.GetAtomicNum() == 6:
                if a.GetIsotope() == 1: 
                    #print(f'Ignoring {smi} due to C-1') 
                    break # if 1C -> assume not buyable
                elif a.GetIsotope() in [2,3,4,5]:
                    replace_dict[i+1] = get_smarts_for_atom(mol_copy, a.GetIdx(), a.GetIsotope())
                    a.SetIsotope(0)
                    a.SetNumExplicitHs(0)

            elif a.GetIsotope(): 

                a.SetNumExplicitHs(0)
                a.SetIsotope(0)
        
        else:
            # remove isotope labels to heteroatoms, add explicit Hs to non-abstracted groups
            smarts = Chem.MolToSmarts(Chem.MolFromSmarts(Chem.MolToSmiles(mol))) 
            for i, a in replace_dict.items():
                smarts = smarts.replace(f':{i}]', f'{a}:{i}]')
            smarts_list.append(smarts.replace('[#54', '[#8,#16').replace('[#85', '[#6'))
            
    return smarts_list