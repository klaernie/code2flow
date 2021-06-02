import abc
import os


TRUNK_COLOR = '#966F33'
LEAF_COLOR = '#6db33f'
EDGE_COLOR = "#cf142b"
NODE_COLOR = "#cccccc"


class Namespace(dict):
    """
    Abstract constants class
    Constants can be accessed via .attribute or [key] and can be iterated over.
    """
    def __init__(self, *args, **kwargs):
        d = {k: k for k in args}
        d.update(dict(kwargs.items()))
        super().__init__(d)

    def __getattr__(self, item):
        return self[item]


OWNER_CONST = Namespace("UNKNOWN_VAR", "UNKNOWN_MODULE", "KNOWN_MODULE")


def is_installed(executable_cmd):
    """
    Determine whether a command can be run or not

    :param list[str] individual_files:
    :rtype: str
    """
    for path in os.environ["PATH"].split(os.pathsep):
        path = path.strip('"')
        exe_file = os.path.join(path, executable_cmd)
        if os.path.isfile(exe_file) and os.access(exe_file, os.X_OK):
            return True
    return False


def djoin(*tup):
    """Convenience method to join strings with dots"""
    return '.'.join(tup)


def flatten(list_of_lists):
    """
    Return a list from a list of lists
    :param list[list[Value]] list_of_lists:
    :rtype: list[Value]
    """
    return [el for sublist in list_of_lists for el in sublist]


def _resolve_str_variable(variable, file_groups):
    """
    String variables are when variable.points_to is a string
    This happens ONLY when we have imports that we delayed processing for
    This function looks through all processed files to see if we can find a match

    :param Variable variable:
    :param list[Group] file_groups:
    :rtype: Node|str
    """
    has_known = False

    for file_group in file_groups:
        # Check if any top level node in the other file matches the import
        for node in file_group.nodes:
            if djoin(file_group.token, node.token) == variable.points_to:
                return node
        # Check if any top level class in the other file matches the import
        for group in file_group.subgroups:
            if djoin(file_group.token, group.token) == variable.points_to \
               and group.get_constructor():
                return group.get_constructor()
        if file_group.token == variable.points_to.split('.', 1)[0]:
            has_known = True
    if has_known:
        return OWNER_CONST.KNOWN_MODULE

    return OWNER_CONST.UNKNOWN_MODULE  # Default indicates we must skip


class BaseLanguage(abc.ABC):
    """
    Languages are individual implementations for different dynamic languages.
    This is the superclass of Python, Javascript, PHP, and Ruby.
    Every implementation must implement all of these methods.
    For more detail, see the individual implementations.
    Note that the 'Tree' type is generic and will be a different
    type for different languages. In Python, it is an ast.AST.
    """

    @staticmethod
    @abc.abstractmethod
    def assert_dependencies():
        """"""

    @staticmethod
    @abc.abstractmethod
    def get_tree(filename, lang_params):
        """
        :param filename str:
        :rtype: Tree
        """

    @staticmethod
    @abc.abstractmethod
    def separate_namespaces(tree):
        """
        :param tree Tree:
        :rtype: (list[tree], list[tree], list[tree])
        """

    @staticmethod
    @abc.abstractmethod
    def make_nodes(tree, parent):
        """
        :param tree Tree:
        :param parent Group:
        :rtype: list[Node]
        """

    @staticmethod
    @abc.abstractmethod
    def make_root_node(lines, parent):
        """
        :param lines list[Tree]:
        :param parent Group:
        :rtype: Node
        """

    @staticmethod
    @abc.abstractmethod
    def make_class_group(tree, parent):
        """
        :param tree Tree:
        :param parent Group:
        :rtype: Group
        """


class Variable():
    """
    Variables represent named tokens that are accessible to their scope.
    They may either point to a string or, once resolved, a Group/Node.
    Not all variables can be resolved
    """
    def __init__(self, token, points_to, line_number=None):
        self.token = token
        self.points_to = points_to
        self.line_number = line_number

    def __repr__(self):
        return f"<Variable token={self.token} points_to={repr(self.points_to)}"

    def to_string(self):
        if self.points_to and isinstance(self.points_to, Group):
            return f'{self.token}->{self.points_to.token}'
        if self.points_to:
            return f'{self.token}->"{self.points_to}"'
        return self.token


class Call():
    """
    Calls represent function call expressions.
    They can be an attribute call like
        object.do_something()
    Or a "naked" call like
        do_something()

    """
    def __init__(self, token, line_number=None, owner_token=None, definite_constructor=False):
        self.token = token
        self.owner_token = owner_token
        self.line_number = line_number
        self.definite_constructor = definite_constructor

    def __repr__(self):
        return f"<Call owner_token={self.owner_token} token={self.token}>"

    def to_string(self):
        """
        Returns a representation of this call to be printed by the engine
        in logging.
        """
        if self.owner_token:
            return f"{self.owner_token}.{self.token}()"
        return f"{self.token}()"

    def is_attr(self):
        """
        Attribute calls are like `a.do_something()` rather than `do_something()`
        """
        return self.owner_token is not None

    def matches_variable(self, variable):
        """
        Check whether this variable is what the call is acting on.
        For example, if we had 'obj' from
            obj = Obj()
        as a variable and a call of
            obj.do_something()
        Those would match and we would return the "do_something" node from obj.

        :param variable Variable:
        :rtype: Node
        """
        # if self.token == 'majorNum' and self.owner_token:
        #     print('\a'); import ipdb; ipdb.set_trace()

        if self.is_attr():
            if self.owner_token == variable.token:
                for node in getattr(variable.points_to, 'nodes', []):
                    if self.token == node.token:
                        return node
                for inherit_cls in getattr(variable.points_to, 'inherits', []):
                    for node in inherit_cls.nodes:
                        if self.token == node.token:
                            return node
                if variable.points_to in OWNER_CONST:
                    return variable.points_to
            return None
        if self.token == variable.token:
            if isinstance(variable.points_to, Node):
                return variable.points_to
            if isinstance(variable.points_to, Group) \
               and variable.points_to.group_type == 'CLASS' \
               and variable.points_to.get_constructor():
                return variable.points_to.get_constructor()
        if variable.points_to == OWNER_CONST.KNOWN_MODULE:
            return OWNER_CONST.KNOWN_MODULE

        return None


class Node():
    # TODO for other languages line number needs to go 2nd-to-last now in the params
    def __init__(self, token, calls, variables, parent, line_number=None, is_constructor=False):
        self.token = token
        self.line_number = line_number
        self.calls = calls
        self.variables = variables
        self.parent = parent
        self.is_constructor = is_constructor

        self.uid = "node_" + os.urandom(4).hex()

        # Assume it is a leaf and a trunk. These are modified later
        self.is_leaf = True  # it calls nothing else
        self.is_trunk = True  # nothing calls it

    def __repr__(self):
        return f"<Node token={self.token} parent={self.parent}>"

    def name(self):
        """
        Names exist largely for unit tests
        """
        return f"{self.group_parent().filename()}::{self.token_with_ownership()}"

    def group_parent(self):
        parent = self.parent
        while type(parent) != Group:
            parent = parent.parent
        return parent

    def root_parent(self):
        parent = self.parent
        while parent.parent:
            parent = parent.parent
        return parent

    def is_method(self):
        return (self.parent
                and isinstance(self.parent, Group)
                and self.parent.group_type == 'CLASS')

    def token_with_ownership(self):
        """
        Token which includes what group this is a part of
        """
        if self.is_method():
            return djoin(self.parent.token, self.token)
        return self.token

    def label(self):
        """
        Labels are what you see on the graph
        """
        if self.line_number is not None:
            return f"{self.line_number}: {self.token}()"
        return f"{self.token}()"

    def remove_from_parent(self):
        """
        Remove this node from it's parent. This effectively deletes the node.
        """
        self.group_parent().nodes = [n for n in self.group_parent().nodes if n != self]

    def get_variables(self, line_number=None):
        """
        Get variables in-scope on the line number.
        This includes all local variables as-well-as outer-scope variables
        """
        if line_number is None:
            ret = list(self.variables)
        else:
            # TODO variables should be sorted by scope before line_number
            ret = list([v for v in self.variables if v.line_number <= line_number])
        if any(v.line_number for v in ret):
            ret.sort(key=lambda v: v.line_number, reverse=True)

        parent = self.parent
        while parent:
            ret += parent.get_variables()
            parent = parent.parent
        return ret

    def resolve_variables(self, file_groups):
        """
        For all variables, attempt to resolve the Node/Group on points_to.
        There is a good chance this will be unsuccessful.

        :param list[Group] file_groups:
        :rtype: None
        """
        for variable in self.variables:
            if isinstance(variable.points_to, str):
                variable.points_to = _resolve_str_variable(variable, file_groups)
            elif isinstance(variable.points_to, Call):
                if variable.points_to.is_attr() and not variable.points_to.definite_constructor:
                    # Only process Class(); Not a.Class()
                    continue
                for file_group in file_groups:
                    for group in file_group.all_groups():
                        if group.token == variable.points_to.token:
                            variable.points_to = group

    def to_dot(self):
        """
        Output for graphviz (.dot) files
        """
        attributes = {
            'label': self.label(),
            'name': self.name(),
            'shape': "rect",
            'style': 'rounded,filled',
            'fillcolor': NODE_COLOR,
        }
        if self.is_trunk:
            attributes['fillcolor'] = TRUNK_COLOR
        elif self.is_leaf:
            attributes['fillcolor'] = LEAF_COLOR

        ret = self.uid + ' ['
        for k, v in attributes.items():
            ret += f'{k}="{v}" '
        ret += ']'
        return ret

    def to_dict(self):
        """
        Output for json files (json graph specification)
        """
        return {
            'uid': self.uid,
            'label': self.label(),
            'name': self.name(),
        }


def _wrap_as_variables(sequence):
    """
    Given a list of either Nodes or Groups, wrap them in variables.
    This is used in the get_variables method to allow all defined
    functions and classes to be defined as variables
    :param list[Group|Node] sequence:
    :rtype: list[Variable]
    """
    return [Variable(el.token, el, el.line_number) for el in sequence]


class Edge():
    def __init__(self, node0, node1):
        self.node0 = node0
        self.node1 = node1

        # When we draw the edge, we know the calling function is definitely not a leaf...
        # and the called function is definitely not a trunk
        node0.is_leaf = False
        node1.is_trunk = False

    def __repr__(self):
        return f"<Edge {self.node0} -> {self.node1}"

    def to_dot(self):
        '''
        Returns string format for embedding in a dotfile. Example output:
        node_uid_a -> node_uid_b [color='#aaa' penwidth='2']
        '''
        ret = self.node0.uid + ' -> ' + self.node1.uid
        ret += f' [color="{EDGE_COLOR}" penwidth="2"]'
        return ret

    def to_dict(self):
        return {
            'source': self.node0.uid,
            'target': self.node1.uid,
            'directed': True,
        }


class Group():
    """
    Groups represent namespaces (classes and modules/files)
    """
    # TODO here too with the line_number
    def __init__(self, token, group_type, line_number=None, parent=None,
                 inherits=None):
        self.token = token
        self.line_number = line_number
        self.nodes = []
        self.root_node = None
        self.subgroups = []
        self.parent = parent
        self.group_type = group_type
        self.inherits = inherits or []
        assert group_type in ('MODULE', 'SCRIPT', 'CLASS')

        self.uid = "cluster_" + os.urandom(4).hex()  # group doesn't work by syntax rules

    def __repr__(self):
        return f"<Group token={self.token} type={self.group_type}>"

    def label(self):
        """
        Labels are what you see on the graph
        """
        return f"{self.group_type}: {self.token}"

    def filename(self):
        """
        The ultimate filename of this group.
        """
        if self.group_type in ('MODULE', 'SCRIPT'):
            return self.token
        return self.parent.filename()

    def add_subgroup(self, sg):
        """
        Subgroups are found after initialization. This is how they are added.
        :param sg Group:
        """
        self.subgroups.append(sg)

    def add_node(self, node, is_root=False):
        """
        Nodes are found after initialization. This is how they are added.
        :param node Node:
        :param is_root bool:
        """
        self.nodes.append(node)
        if is_root:
            self.root_node = node

    def all_nodes(self):
        """
        List of nodes that are part of this group + all subgroups
        :rtype: list[Node]
        """
        ret = list(self.nodes)
        for subgroup in self.subgroups:
            ret += subgroup.all_nodes()
        return ret

    def get_constructor(self):
        """
        Return the first constructor for this group - if any
        TODO, this excludes the possibility of multiple constructors
        :rtype: Node|None
        """
        assert self.group_type == 'CLASS'
        constructors = [n for n in self.nodes if n.is_constructor]
        if constructors:
            return constructors[0]

    def all_groups(self):
        """
        List of groups that are part of this group + all subgroups
        :rtype: list[Group]
        """
        ret = [self]
        for subgroup in self.subgroups:
            ret += subgroup.all_groups()
        return ret

    def get_variables(self, line_number=None):
        """
        Get in-scope variables from this group.
        This assumes every variable will be in-scope in nested functions
        line_number is included for compatibility with Node.get_variables but is not used

        :param int line_number:
        :rtype: list[Variable]
        """

        if self.root_node:
            variables = (self.root_node.variables
                         + _wrap_as_variables(self.subgroups)
                         + _wrap_as_variables(n for n in self.nodes if n != self.root_node))
            if any(v.line_number for v in variables):
                return sorted(variables, key=lambda v: v.line_number, reverse=True)
            return variables
        else:
            return []

    def remove_from_parent(self):
        """
        Remove this group from it's parent. This is effectively a deletion
        """
        if self.parent:
            self.parent.subgroups = [g for g in self.parent.subgroups if g != self]

    def to_dot(self):
        """
        Returns string format for embedding in a dotfile. Example output:
        subgraph group_uid_a {
            node_uid_b node_uid_c;
            label='class_name';
            ...
            subgraph group_uid_z {
                ...
            }
            ...
        }
        """

        ret = 'subgraph ' + self.uid + ' {\n'
        if self.nodes:
            ret += '    '
            ret += ' '.join(node.uid for node in self.nodes)
            ret += ';\n'
        attributes = {
            'label': self.label(),
            'name': self.token,
            'style': 'filled',
        }
        for k, v in attributes.items():
            ret += f'    {k}="{v}";\n'
        ret += '    graph[style=dotted];\n'
        for subgroup in self.subgroups:
            ret += '    ' + ('\n'.join('    ' + ln for ln in
                                       subgroup.to_dot().split('\n'))).strip() + '\n'
        ret += '};\n'
        return ret
