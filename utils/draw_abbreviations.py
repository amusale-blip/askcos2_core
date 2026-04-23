CUSTOM_ABBREVIATIONS = '''
NHCF3 *[NH]C(F)(F)F NHCF<sub>3</sub> F<sub>3</sub>CNH
NHMe *[NH]C NHMe MeNH
'''

# Isotope + element symbol -> RDKit atom label (supports <sup> / <sub> markup).
CARBON_ABS_LABELS = {
    "1C": "[C-C]",
    "2C": "[C=C]",
    "3C": "[C#C]",
    "4C": "[C<sup>(+)</sup>]",
    "5C": "[C<sup>(-)</sup>]",
}

# Plain-text equivalents for use as Ketcher/molfile atom aliases (no HTML markup).
KETCHER_ABS_LABELS = {
    "1C": "[C-C]",
    "2C": "[C=C]",
    "3C": "[C#C]",
    "4C": "[C(+)]",
    "5C": "[C(-)]",
}
