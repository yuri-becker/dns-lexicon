from os.path import abspath, dirname, join

import tomllib

with open(join(dirname(dirname(abspath(__file__))), "pyproject.toml"), "rb") as file_h:
    metadata = tomllib.load(file_h)["project"]

master_doc = 'index'
project = "DNS-Lexicon"
version = release = metadata["version"]

extensions = [
    "sphinx_rtd_theme",
]

html_theme = "sphinx_rtd_theme"
