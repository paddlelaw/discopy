# -*- coding: utf-8 -*-

"""
Implements quantum circuits as diagrams and circuit-valued monoidal functors.

>>> n = Ty('n')
>>> Alice = Box('Alice', Ty(), n)
>>> loves = Box('loves', n, n)
>>> Bob = Box('Bob', n, Ty())
>>> ob, ar = {n: 1}, {Alice: Ket(0), loves: X, Bob: Bra(1)}
>>> F = CircuitFunctor(ob, ar)
>>> print(F(Alice >> loves >> Bob))
Ket(0) >> X >> Bra(1)
>>> assert F(Alice >> loves >> Bob).eval()
"""

import random as rand
from discopy import messages
from discopy.cat import Quiver
from discopy.rigidcat import Ob, Ty, Box, Diagram, RigidFunctor
from discopy.matrix import np, Dim, Matrix, MatrixFunctor


class PRO(Ty):
    """ Implements the objects of a PRO, i.e. a non-symmetric PROP.
    Wraps a natural number n into a unary type Ty(1, ..., 1) of length n.

    >>> PRO(1) @ PRO(1)
    PRO(2)
    >>> assert PRO(3) == Ty(1, 1, 1)
    """
    def __init__(self, n=0):
        super().__init__(*(n * [1]))

    @property
    def l(self):
        """
        >>> assert PRO(2).l == PRO(2)
        """
        return self

    @property
    def r(self):
        return self

    def tensor(self, other):
        return PRO(len(self) + len(other))

    def __repr__(self):
        return "PRO({})".format(len(self))

    def __str__(self):
        return repr(len(self))

    def __getitem__(self, key):
        if isinstance(key, slice):
            return PRO(len(super().__getitem__(key)))
        return super().__getitem__(key)


class Circuit(Diagram):
    """
    Implements quantum circuits as diagrams.
    """
    @staticmethod
    def _upgrade(diagram):
        """
        Takes a diagram and returns a circuit.
        """
        return Circuit(len(diagram.dom), len(diagram.cod),
                       diagram.boxes, diagram.offsets, diagram.layers)

    def __init__(self, dom, cod, gates, offsets, layers=None):
        """
        >>> c = Circuit(2, 2, [CX, CX], [0, 0])
        """
        self._gates = gates
        super().__init__(PRO(dom), PRO(cod), gates, offsets, layers)

    def __repr__(self):
        """
        >>> Circuit(2, 2, [CX, CX], [0, 0])  # doctest: +ELLIPSIS
        Circuit(dom=PRO(2), cod=PRO(2), ...)
        >>> Circuit(2, 2, [CX, CX], [0, 0])  # doctest: +ELLIPSIS
        Circuit(..., boxes=[Gate('CX', ...), Gate('CX', ...)], offsets=[0, 0])
        >>> Circuit(2, 2, [CX], [0])  # doctest: +ELLIPSIS
        Gate('CX', 2, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0])
        >>> Circuit(2, 2, [], [])
        Id(2)
        """
        return super().__repr__().replace('Diagram', 'Circuit')

    @property
    def gates(self):
        """
        >>> Circuit(1, 1, [X, X], [0, 0]).gates
        [Gate('X', 1, [0, 1, 1, 0]), Gate('X', 1, [0, 1, 1, 0])]
        """
        return self._gates

    @staticmethod
    def id(x):
        """
        >>> Circuit.id(2)
        Id(2)
        """
        return Id(x)

    @staticmethod
    def cups(left, right):
        """
        >>> list(np.round(Circuit.cups(PRO(1), PRO(1)).eval().array.flatten()))
        [1.0, 0.0, 0.0, 1.0]
        """
        if not isinstance(left, PRO):
            raise TypeError(messages.type_err(PRO, left))
        if not isinstance(right, PRO):
            raise TypeError(messages.type_err(PRO, right))
        result = Id(left @ right)
        cup = CX >> H @ sqrt(2) @ Id(1) >> Bra(0, 0)
        for i in range(1, len(left) + 1):
            result = result >> Id(len(left) - i) @ cup @ Id(len(left) - i)
        return result

    @staticmethod
    def caps(left, right):
        """
        >>> list(np.round(Circuit.caps(PRO(1), PRO(1)).eval().array.flatten()))
        [1.0, 0.0, 0.0, 1.0]
        """
        return Circuit.cups(left, right).dagger()

    def eval(self):
        """
        Evaluates the circuit as a discopy Matrix.
        """
        return MatrixFunctor({Ty(1): 2}, Quiver(lambda g: g.array))(self)

    def normalize(self):
        """
        >>> circuit = Ket(0) @ sqrt(2) @ Ket(1) @ sqrt(2) >> CX >> Id(1) @ Ket(0) @ Id(1)
        >>> gen = circuit.normalize()
        >>> print(next(gen))
        >>> print(next(gen))
        >>> print(next(gen))
        >>> print(next(gen))
        """
        # step 2: move kets to the bottom of the diagram
        # step 3: get first slice of the foliation
        # step 4: fuse kets
        # step 5: repeat with .dagger() for bras
        def remove_scalars(diagram):
            for i, box in enumerate(diagram.boxes):
                if box.dom == box.cod == PRO():
                    return diagram[:i] >> diagram[i + 1:], box.array[0]
            return diagram, None

        def move_ket(diagram, i):
            try:
                diagram.interchange(i, i - 1)
                return diagram, i - 1
            except InterchangerError:
                left = diagram.layers[i].left
                right = diagram.layers[i].right
                layer = Id(left[:-1])\
                    @ (diagram.boxes[i] @ Id(left[-1]) >> SWAP)\
                    @ Id(right)
                return diagram[:i] >> layer >> diagram[i + 1:], i

        diagram = self
        # step 1: remove scalars from diagram
        scalar = 1
        while True:
            diagram, number = remove_scalars(diagram)
            if number is None:
                break
            scalar = scalar * number
            yield diagram, scalar

        # step 2: move kets to the bottom of the diagram
        slices = diagram.foliation()
        _diagram, i = slices[1:].flatten(), 0
        while i < len(_diagram):
            if isinstance(box, Ket):
                _diagram, i = move_ket(_diagram, i)
                yield slices.boxes[0] >> _diagram
            else:
                i += 1

    def measure(self):
        """
        Applies the Born rule and outputs a stochastic matrix.
        The input maybe any circuit c, the output will be a numpy array
        with shape len(c.dom @ c.cod) * (2, )

        >>> m = X.measure()
        >>> list(np.round(m[0].flatten()))
        [0.0, 1.0]
        >>> assert (Ket(0) >> X >> Bra(1)).measure() == m[0, 1]
        """
        def bitstring(i, length):
            return map(int, '{{:0{}b}}'.format(length).format(i))
        process = self.eval()
        states, effects = [], []
        states = [Ket(*bitstring(i, len(self.dom))).eval()
                  for i in range(2 ** len(self.dom))]
        effects = [Bra(*bitstring(j, len(self.cod))).eval()
                   for j in range(2 ** len(self.cod))]
        array = np.zeros(len(self.dom + self.cod) * (2, ))
        for state in states if self.dom else [Matrix.id(1)]:
            for effect in effects if self.cod else [Matrix.id(1)]:
                scalar = np.absolute((state >> process >> effect).array ** 2)
                array += scalar * (state.dagger() >> effect.dagger()).array
        return array

    def to_tk(self):
        """ Returns a pytket circuit.

        >>> circuit = Circuit(2, 2, [Rz(0.5), Rx(0.25), CX], [0, 1, 0]).to_tk()
        >>> for g in circuit: print((g.op.get_type(), g.op.get_params()))
        (OpType.Rz, [0.5])
        (OpType.Rx, [0.25])
        (OpType.CX, [])
        """
        import pytket as tk
        tk_circuit = tk.Circuit(len(self.dom))
        for gate, off in zip(self.gates, self.offsets):
            if isinstance(gate, Rx):
                tk_circuit.Rx(
                    gate.phase, *(off + i for i in range(len(gate.dom))))
            elif isinstance(gate, Rz):
                tk_circuit.Rz(
                    gate.phase, *(off + i for i in range(len(gate.dom))))
            else:
                tk_circuit.__getattribute__(gate.name)(
                    *(off + i for i in range(len(gate.dom))))
        return tk_circuit

    @staticmethod
    def from_tk(tk_circuit):
        """ Takes a pytket circuit and returns a planar circuit,
        SWAP gates are introduced when applying gates to non-adjacent qubits.

        >>> c1 = Circuit(2, 2, [Rz(0.5), Rx(0.25), CX], [0, 1, 0])
        >>> c2 = Circuit.from_tk(c1.to_tk())
        >>> # assert c1.normal_form() == c2.normal_form()
        """
        def gates_from_tk(tk_gate):
            name = tk_gate.op.get_type().name
            if name == 'Rx':
                return Rx(tk_gate.op.get_params()[0])
            if name == 'Rz':
                return Rz(tk_gate.op.get_params()[0])
            for gate in [SWAP, CX, H, S, T, X, Y, Z]:
                if name == gate.name:
                    return gate
            raise NotImplementedError
        gates, offsets = [], []
        for tk_gate in tk_circuit.get_commands():
            i_0 = tk_gate.qubits[0].index[0]
            for i, qubit in enumerate(tk_gate.qubits[1:]):
                if qubit.index[0] == i_0 + i + 1:
                    break  # gate applies to adjacent qubit already
                if qubit.index[0] < i_0 + i + 1:
                    for j in range(qubit.index[0], i_0 + i):
                        gates.append(SWAP)
                        offsets.append(j)
                    if qubit.index[0] <= i_0:
                        i_0 -= 1
                else:
                    for j in range(qubit.index[0] - i_0 + i - 1):
                        gates.append(SWAP)
                        offsets.append(qubit.index[0] - j - 1)
            gates.append(gates_from_tk(tk_gate))
            offsets.append(i_0)
        return Circuit(tk_circuit.n_qubits, tk_circuit.n_qubits,
                       gates, offsets)

    @staticmethod
    def random(n_qubits, depth=3, gateset=None, seed=None):
        """ Returns a random Euler decomposition if n_qubits == 1,
        otherwise returns a random tiling with the given depth and gateset.

        >>> c = Circuit.random(1, seed=420)
        >>> print(c)  # doctest: +ELLIPSIS
        Rx(0.026...) >> Rz(0.781...) >> Rx(0.272...)
        >>> print(Circuit.random(2, 2, gateset=[CX, H, T], seed=420))
        CX >> T @ Id(1) >> Id(1) @ T
        >>> print(Circuit.random(3, 2, gateset=[CX, H, T], seed=420))
        CX @ Id(1) >> Id(2) @ T >> H @ Id(2) >> Id(1) @ H @ Id(1) >> Id(2) @ H
        >>> print(Circuit.random(2, 1, gateset=[Rz, Rx], seed=420))
        Rz(0.6731171219152886) @ Id(1) >> Id(1) @ Rx(0.2726063832840899)
        """
        if seed is not None:
            rand.seed(seed)
        if n_qubits == 1:
            return Rx(rand.random()) >> Rz(rand.random()) >> Rx(rand.random())
        result = Id(n_qubits)
        for _ in range(depth):
            line, n_affected = Id(0), 0
            while n_affected < n_qubits:
                gate = rand.choice(
                    gateset if n_qubits - n_affected > 1 else [
                        g for g in gateset
                        if g is Rx or g is Rz or len(g.dom) == 1])
                if gate is Rx or gate is Rz:
                    gate = gate(rand.random())
                line = line @ gate
                n_affected += len(gate.dom)
            result = result >> line
        return result


class Id(Circuit):
    """ Implements identity circuit on n qubits.

    >>> c = CX @ H >> T @ SWAP
    >>> assert Id(3) >> c == c == c >> Id(3)
    """
    def __init__(self, n_qubits):
        """
        >>> assert Circuit.id(42) == Id(42) == Circuit(42, 42, [], [])
        """
        if isinstance(n_qubits, PRO):
            n_qubits = len(n_qubits)
        super().__init__(n_qubits, n_qubits, [], [])

    def __repr__(self):
        """
        >>> Id(42)
        Id(42)
        """
        return "Id({})".format(len(self.dom))

    def __str__(self):
        """
        >>> print(Id(42))
        Id(42)
        """
        return repr(self)


class Gate(Box, Circuit):
    """ Implements quantum gates as boxes in a circuit diagram.

    >>> CX
    Gate('CX', 2, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0])
    """
    def __init__(self, name, n_qubits, array=None, data=None, _dagger=False):
        """
        >>> g = CX
        >>> assert g.dom == g.cod == PRO(2)
        """
        if array is not None:
            self._array = np.array(array).reshape(2 * n_qubits * (2, ) or 1)
        Box.__init__(self, name, PRO(n_qubits), PRO(n_qubits),
                     data=data, _dagger=_dagger)
        Circuit.__init__(self, n_qubits, n_qubits, [self], [0])

    @property
    def array(self):
        """
        >>> list(X.array.flatten())
        [0, 1, 1, 0]
        """
        return self._array

    def __repr__(self):
        """
        >>> CX
        Gate('CX', 2, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0])
        >>> X.dagger()
        Gate('X', 1, [0, 1, 1, 0])
        >>> Y.dagger()
        Gate('Y', 1, [0j, (-0-1j), 1j, 0j]).dagger()
        """
        if self._dagger:
            return repr(self.dagger()) + '.dagger()'
        return "Gate({}, {}, {}{})".format(
            repr(self.name), len(self.dom), list(self.array.flatten()),
            ', data=' + repr(self.data) if self.data else '')

    def dagger(self):
        """
        >>> print(CX.dagger())
        CX
        >>> print(Y.dagger())
        Y[::-1]
        >>> assert Y.eval().dagger() == Y.dagger().eval()
        """
        return Gate(
            self.name, len(self.dom), self.array, data=self.data,
            _dagger=None if self._dagger is None else not self._dagger)


class Ket(Box, Circuit):
    """ Implements ket for a given bitstring.

    >>> Ket(1, 1, 0).eval()
    Matrix(dom=Dim(1), cod=Dim(2, 2, 2), array=[0, 0, 0, 0, 0, 0, 1, 0])
    """
    def __init__(self, *bitstring):
        """
        >>> g = Ket(1, 1, 0)
        """
        self.bitstring = bitstring
        Box.__init__(self, 'Ket({})'.format(', '.join(map(str, bitstring))),
                     PRO(0), PRO(len(bitstring)))
        Circuit.__init__(self, 0, len(bitstring), [self], [0])

    def tensor(self, other):
        """
        When two Kets are tensored together, they yield one big Ket with the
        concatenation of their bitstrings.

        >>> Ket(0, 1, 0) @ Ket(1, 0)
        Ket(0, 1, 0, 1, 0)
        >>> assert isinstance(Ket(1) @ Id(1) @ Ket(1, 0), Circuit)
        """
        if isinstance(other, Ket):
            return Ket(*(self.bitstring + other.bitstring))
        return super().tensor(other)

    def __repr__(self):
        """
        >>> Ket(1, 1, 0)
        Ket(1, 1, 0)
        """
        return self.name

    def dagger(self):
        """
        >>> Ket(0, 1).dagger()
        Bra(0, 1)
        """
        return Bra(*self.bitstring)

    @property
    def array(self):
        """
        >>> Ket(0).eval()
        Matrix(dom=Dim(1), cod=Dim(2), array=[1, 0])
        >>> Ket(0, 1).eval()
        Matrix(dom=Dim(1), cod=Dim(2, 2), array=[0, 1, 0, 0])
        """
        matrix = Matrix(Dim(1), Dim(1), [1])
        for bit in self.bitstring:
            matrix = matrix @ Matrix(Dim(2), Dim(1), [0, 1] if bit else [1, 0])
        return matrix.array


class Bra(Box, Circuit):
    """ Implements bra for a given bitstring.

    >>> Bra(1, 1, 0).eval()
    Matrix(dom=Dim(2, 2, 2), cod=Dim(1), array=[0, 0, 0, 0, 0, 0, 1, 0])
    >>> assert all((Bra(x, y, z) << Ket(x, y, z)).eval() == 1
    ...            for x in [0, 1] for y in [0, 1] for z in [0, 1])
    """
    def __init__(self, *bitstring):
        """
        >>> g = Bra(1, 1, 0)
        """
        self.bitstring = bitstring
        Box.__init__(self, 'Bra({})'.format(', '.join(map(str, bitstring))),
                     PRO(len(bitstring)), PRO(0))
        Circuit.__init__(self, len(bitstring), 0, [self], [0])

    def __repr__(self):
        """
        >>> Bra(1, 1, 0)
        Bra(1, 1, 0)
        """
        return self.name

    def tensor(self, other):
        """
        When two Bras are tensored together, they yield one big Bra with the
        concatenation of their bitstrings.

        >>> Bra(0, 1, 0) @ Bra(1, 0)
        Bra(0, 1, 0, 1, 0)
        >>> print(Bra(0) @ X)
        Bra(0) @ Id(1) >> X
        """
        if isinstance(other, Bra):
            return Bra(*(self.bitstring + other.bitstring))
        return super().tensor(other)

    def dagger(self):
        """
        >>> Bra(0, 1).dagger()
        Ket(0, 1)
        """
        return Ket(*self.bitstring)

    @property
    def array(self):
        """
        >>> Bra(0).eval()
        Matrix(dom=Dim(2), cod=Dim(1), array=[1, 0])
        >>> Bra(0, 1).eval()
        Matrix(dom=Dim(2, 2), cod=Dim(1), array=[0, 1, 0, 0])
        """
        return Ket(*self.bitstring).array


class Rz(Gate):
    """
    >>> assert np.all(Rz(0).array == np.identity(2))
    >>> assert np.allclose(Rz(0.5).array, Z.array)
    >>> assert np.allclose(Rz(0.25).array, S.array)
    >>> assert np.allclose(Rz(0.125).array, T.array)
    """
    def __init__(self, phase):
        """
        >>> Rz(0.25)
        Rz(0.25)
        """
        self._phase = phase
        super().__init__('Rz', 1)

    @property
    def phase(self):
        """
        >>> Rz(0.25).phase
        0.25
        """
        return self._phase

    @property
    def name(self):
        """
        >>> assert str(Rz(0.125)) == repr(Rz(0.125)) == Rz(0.125).name
        """
        return 'Rz({})'.format(self.phase)

    def __repr__(self):
        """
        >>> assert str(Rz(0.125)) == repr(Rz(0.125))
        """
        return self.name

    def dagger(self):
        """
        >>> assert Rz(0.5).dagger().eval() == Rz(0.5).eval().dagger()
        """
        return Rz(-self.phase)

    @property
    def array(self):
        """
        >>> assert np.allclose(Rz(0.5).array, Z.array)
        """
        theta = 2 * np.pi * self.phase
        return np.array([[1, 0], [0, np.exp(1j * theta)]])


class Rx(Gate):
    """
    >>> assert np.all(np.round(Rx(0.5).array) == X.array)
    """
    def __init__(self, phase):
        """
        >>> Rx(0.25)
        Rx(0.25)
        """
        self._phase = phase
        super().__init__('Rx', 1)

    @property
    def phase(self):
        """
        >>> Rx(0.25).phase
        0.25
        """
        return self._phase

    @property
    def name(self):
        """
        >>> assert str(Rx(0.125)) == Rx(0.125).name
        """
        return 'Rx({})'.format(self.phase)

    def __repr__(self):
        """
        >>> assert str(Rx(0.125)) == repr(Rx(0.125))
        """
        return self.name

    def dagger(self):
        """
        >>> assert Rx(0.5).dagger().eval() == Rx(0.5).eval().dagger()
        """
        return Rx(-self.phase)

    @property
    def array(self):
        half_theta = np.pi * self.phase
        global_phase = np.exp(1j * half_theta)
        sin, cos = np.sin(half_theta), np.cos(half_theta)
        return global_phase * np.array([[cos, -1j * sin], [-1j * sin, cos]])


class CircuitFunctor(RigidFunctor):
    """ Implements funtors from monoidal categories to circuits

    >>> x, y, z = Ty('x'), Ty('y'), Ty('z')
    >>> f, g, h = Box('f', x, y + z), Box('g', z, y), Box('h', y + z, x)
    >>> d = (f @ Diagram.id(z)
    ...       >> Diagram.id(y) @ g @ Diagram.id(z)
    ...       >> Diagram.id(y) @ h)
    >>> ob = {x: 2, y: 1, z: 1}
    >>> ar = {f: SWAP, g: Rx(0.25), h: CX}
    >>> F = CircuitFunctor(ob, ar)
    >>> print(F(d))
    SWAP @ Id(1) >> Id(1) @ Rx(0.25) @ Id(1) >> Id(1) @ CX
    """
    def __init__(self, ob, ar):
        super().__init__(ob, ar, ob_cls=PRO, ar_cls=Circuit)

    def __repr__(self):
        """
        >>> CircuitFunctor({}, {})
        CircuitFunctor(ob={}, ar={})
        """
        return "CircuitFunctor(ob={}, ar={})".format(
            repr(self.ob), repr(self.ar))

    def __call__(self, diagram):
        """
        >>> x = Ty('x')
        >>> F = CircuitFunctor({x: 1}, {})
        >>> assert isinstance(F(Diagram.id(x)), Circuit)
        """
        if isinstance(diagram, Ob) and not diagram.z:
            return PRO(self.ob[Ty(diagram.name)])
        result = super().__call__(diagram)
        if isinstance(diagram, Ty):
            return PRO(len(result))
        if isinstance(diagram, Diagram):
            return Circuit._upgrade(result)
        return result


def sqrt(real):
    """
    >>> sqrt(2)  # doctest: +ELLIPSIS
    Gate('sqrt(2)', 0, [1.41...])
    """
    return Gate('sqrt({})'.format(real), 0, np.sqrt(real), _dagger=None)


SWAP = Gate('SWAP', 2, [1, 0, 0, 0,
                        0, 0, 1, 0,
                        0, 1, 0, 0,
                        0, 0, 0, 1], _dagger=None)
CX = Gate('CX', 2, [1, 0, 0, 0,
                    0, 1, 0, 0,
                    0, 0, 0, 1,
                    0, 0, 1, 0], _dagger=None)
H = Gate('H', 1, 1 / np.sqrt(2) * np.array([1, 1, 1, -1]), _dagger=None)
S = Gate('S', 1, [1, 0, 0, 1j])
T = Gate('T', 1, [1, 0, 0, np.exp(1j * np.pi / 4)])
X = Gate('X', 1, [0, 1, 1, 0], _dagger=None)
Y = Gate('Y', 1, [0, -1j, 1j, 0])
Z = Gate('Z', 1, [1, 0, 0, -1], _dagger=None)
