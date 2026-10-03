"""Attribute-first product discovery: find which products offer an attribute value.

Backs the /ask `attribute_search` route ("I want a product that has ATT as
a carrier"). ground.py maps the user's raw phrase onto real catalog
labels; lookup.py searches the Data Table under those labels.
"""
