"""
bsb.config module

Contains the dynamic attribute system; Use ``@bsb.config.root/node/dynamic/pluggable`` to
decorate your classes and add class attributes using ``x =
config.attr/dict/list/ref/reflist`` to populate your classes with powerful attributes.
"""

import os, sys, itertools

_list = list
from ._attrs import (
    attr,
    list,
    dict,
    node,
    root,
    dynamic,
    ref,
    reflist,
    slot,
    pluggable,
    catch_all,
)
from ._make import walk_node_attributes, walk_nodes
from ._hooks import on, before, after, run_hook, has_hook
from .. import plugins
from ..exceptions import *


_path = __path__


class ConfigurationModule:
    from . import types, refs, nodes

    def __init__(self, name):
        self.__name__ = name

    attr = staticmethod(attr)
    list = staticmethod(list)
    dict = staticmethod(dict)
    ref = staticmethod(ref)
    reflist = staticmethod(reflist)
    slot = staticmethod(slot)
    catch_all = staticmethod(catch_all)

    node = staticmethod(node)
    root = staticmethod(root)
    dynamic = staticmethod(dynamic)
    pluggable = staticmethod(pluggable)

    walk_node_attributes = staticmethod(walk_node_attributes)
    walk_nodes = staticmethod(walk_nodes)
    on = staticmethod(on)
    after = staticmethod(after)
    before = staticmethod(before)
    run_hook = staticmethod(run_hook)
    has_hook = staticmethod(has_hook)

    _parser_classes = {}

    # The __path__ attribute needs to be retained to mark this module as a package with
    # submodules (config.nodes, config.refs, config.parsers.json, ...)
    __path__ = _path

    # Load the Configuration class on demand, not on import, to avoid circular
    # dependencies.

    @property
    def Configuration(self):
        if not hasattr(self, "_cfg_cls"):
            from ._config import Configuration

            self._cfg_cls = Configuration
            self._cfg_cls.__module__ = __name__
        return self._cfg_cls

    def get_parser(self, parser_name):
        """
        Create an instance of a configuration parser that can parse configuration
        strings into configuration trees, or serialize trees into strings.

        Configuration trees can be cast into Configuration objects.
        """
        if not parser_name in self._parser_classes:
            raise PluginError("Configuration parser '{}' not found".format(parser_name))
        return self._parser_classes[parser_name]()

    def get_config_path(self):
        import os

        env_paths = os.environ.get("BSB_CONFIG_PATH", None)
        if env_paths is None:
            env_paths = ()
        else:
            env_paths = env_paths.split(":")
        plugin_paths = plugins.discover("config.templates")
        return _list(itertools.chain((os.getcwd(),), env_paths, *plugin_paths.values()))

    def copy_template(self, template, output="network_configuration.json", path=None):
        from shutil import copy2 as copy_file
        import os, glob, itertools

        path = _list(
            map(
                os.path.abspath,
                itertools.chain(self.get_config_path(), path or ()),
            )
        )
        for d in path:
            if (files := glob.glob(os.path.join(d, template))) :
                break
        else:
            raise ConfigTemplateNotFoundError(
                "'%template%' not found in config path %path%", template, path
            )
        copy_file(files[0], output)

    __all__ = _list(vars().keys() - {"__init__", "__qualname__", "__module__"})


def _parser_method_docs(parser):
    mod = parser.__module__
    mod = mod[8:] if mod.startswith("scaffold.") else mod
    class_role = ":class:`{} <{}.{}>`".format(parser.__name__, mod, parser.__name__)
    if parser.data_description:
        descr = " " + parser.data_description
    else:  # pragma: nocover
        descr = ""
    return (
        "Create a Configuration object from"
        + descr
        + " data from an object or file. The data is passed to the "
        + class_role
        + """.

        :param file: Path to a file to read the data from.
        :type file: str
        :param data: Data object to hand directly to the parser
        :type data: any
        :returns: A Configuration
        :rtype: :class:`Configuration <.conf.Configuration>`
    """
    )


def parser_factory(name, parser):
    # This factory produces the methods for the `bsb.config.from_*` parser methods that
    # load the content of a file-like object or a simple string as a Configuration object.
    def parser_method(self, file=None, data=None, path=None):
        if file is not None:
            file = os.path.abspath(file)
            with open(file, "r") as f:
                data = f.read()
        tree, meta = parser().parse(data, path=path or file)
        conf = self.Configuration(tree)
        conf._parser = name
        conf._meta = meta
        conf._file = file
        return conf

    parser_method.__name__ = "from_" + name
    parser_method.__doc__ = _parser_method_docs(parser)
    return parser_method


# Load all the `config.parsers` plugins and create a `from_*` method for them.
for name, parser in plugins.discover("config.parsers").items():
    ConfigurationModule._parser_classes[name] = parser
    setattr(ConfigurationModule, "from_" + name, parser_factory(name, parser))
    ConfigurationModule.__all__.append("from_" + name)

ConfigurationModule.__all__ = sorted(ConfigurationModule.__all__)

sys.modules[__name__] = ConfigurationModule(__name__)