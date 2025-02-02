import unittest, os, sys, numpy as np, h5py
from mpi4py import MPI

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from bsb.core import Scaffold
from bsb.config import Configuration
from bsb.objects import CellType
from bsb.topology import Region, Partition
from bsb.exceptions import *
from bsb.storage import Chunk
from bsb.placement import PlacementStrategy
from bsb._pool import JobPool, FakeFuture, create_job_pool
from test_setup import timeout
from time import sleep


def test_dud(scaffold, x, y):
    sleep(y)
    return x


def test_chunk(scaffold, chunk):
    return chunk


class PlacementDud(PlacementStrategy):
    name = "dud"

    def place(self, chunk, indicators):
        pass


def single_layer_placement(offset=[0.0, 0.0, 0.0]):
    network = Scaffold()
    network.partitions["dud_layer"] = part = Partition(
        name="dud_layer", thickness=120, region="dud_region"
    )
    network.regions["dud_region"] = reg = Region(
        name="dud_region", offset=offset, partitions=[part]
    )
    dud_cell = CellType(name="dud", spatial={"count": 40, "radius": 2})
    network.cell_types["dud"] = dud_cell
    dud = PlacementDud(
        name="dud",
        cls="PlacementDud",
        partitions=[part],
        cell_types=[dud_cell],
        overrides={"dud": {}},
    )
    network.placement["dud"] = dud
    network.configuration._bootstrap(network)
    return dud, network


def _chunk(x, y, z):
    return Chunk((x, y, z), (100, 100, 100))


class TestIndicators(unittest.TestCase):
    def test_cascade(self):
        indicators = dud.get_indicators()
        dud_ind = indicators["dud"]
        self.assertEqual(2, dud_ind.indication("radius"))
        self.assertEqual(40, dud_ind.indication("count"))
        self.assertEqual(2, dud_ind.get_radius())
        dud.overrides.dud.radius = 4
        self.assertEqual(4, dud_ind.indication("radius"))
        dud.overrides.dud.radius = None
        dud.cell_types[0].spatial.radius = None
        self.assertEqual(None, dud_ind.indication("radius"))
        self.assertRaises(IndicatorError, dud_ind.get_radius)

    def test_guess(self):
        dud, network = single_layer_placement()
        indicators = dud.get_indicators()
        dud_ind = indicators["dud"]
        self.assertEqual(40, dud_ind.guess())
        dud.overrides.dud.count = 400
        self.assertEqual(400, dud_ind.guess())
        bottom_ratio = 1 / 1.2
        bottom = 400 * bottom_ratio / 4
        top_ratio = 0.2 / 1.2
        top = 400 * top_ratio / 4
        for x, y, z in ((0, 0, 0), (0, 0, 1), (1, 0, 0), (1, 0, 1)):
            with self.subTest(x=x, y=y, z=z):
                guess = dud_ind.guess(_chunk(x, y, z))
                self.assertTrue(np.floor(bottom) <= guess <= np.ceil(bottom))
        for x, y, z in ((0, 1, 0), (0, 1, 1), (1, 1, 0), (1, 1, 1)):
            with self.subTest(x=x, y=y, z=z):
                guess = dud_ind.guess(_chunk(x, y, z))
                self.assertTrue(np.floor(top) <= guess <= np.ceil(top))
        for x, y, z in ((0, -1, 0), (0, 2, 0), (2, 1, 0), (1, 1, -3)):
            with self.subTest(x=x, y=y, z=z):
                guess = dud_ind.guess(_chunk(x, y, z))
                self.assertEqual(0, guess)

    def test_negative_guess(self):
        dud, network = single_layer_placement(offset=np.array([-300.0, -300.0, -300.0]))
        indicators = dud.get_indicators()
        dud_ind = indicators["dud"]
        bottom_ratio = 1 / 1.2
        bottom = 40 * bottom_ratio / 4
        top_ratio = 0.2 / 1.2
        top = 40 * top_ratio / 4
        for x, y, z in ((-3, -3, -3), (-3, -3, -2), (-2, -3, -3), (-2, -3, -2)):
            with self.subTest(x=x, y=y, z=z):
                guess = dud_ind.guess(_chunk(x, y, z))
                self.assertTrue(np.floor(bottom) <= guess <= np.ceil(bottom))
        for x, y, z in ((-3, -2, -3), (-3, -2, -2), (-2, -2, -3), (-2, -2, -2)):
            with self.subTest(x=x, y=y, z=z):
                guess = dud_ind.guess(_chunk(x, y, z))
                self.assertTrue(np.floor(top) <= guess <= np.ceil(top))
        for x, y, z in ((0, -1, 0), (0, 0, 0), (2, 0, 0), (1, 1, -3)):
            with self.subTest(x=x, y=y, z=z):
                guess = dud_ind.guess(_chunk(x, y, z))
                self.assertEqual(0, guess)


dud, network = single_layer_placement()


class SchedulerBaseTest:
    @timeout(3)
    def test_create_pool(self):
        pool = create_job_pool(network)

    @timeout(3)
    def test_single_job(self):
        pool = JobPool(network)
        job = pool.queue(test_dud, (5, 0.1))
        pool.execute()

    @timeout(3)
    def test_listeners(self):
        i = 0

        def spy(job):
            nonlocal i
            i += 1

        pool = JobPool(network, listeners=[spy])
        job = pool.queue(test_dud, (5, 0.1))
        pool.execute()
        if not MPI.COMM_WORLD.Get_rank():
            self.assertEqual(1, i, "Listeners not executed.")

    def test_placement_job(self):
        pool = JobPool(network)
        job = pool.queue_placement(dud, _chunk(0, 0, 0))
        pool.execute()

    def test_chunked_job(self):
        pool = JobPool(network)
        job = pool.queue_chunk(test_chunk, _chunk(0, 0, 0))
        pool.execute()


@unittest.skipIf(MPI.COMM_WORLD.Get_size() < 2, "Skipped during serial testing.")
class TestParallelScheduler(unittest.TestCase, SchedulerBaseTest):
    @timeout(3)
    def test_double_pool(self):
        pool = JobPool(network)
        job = pool.queue(test_dud, (5, 0.1))
        pool.execute()
        pool = JobPool(network)
        job = pool.queue(test_dud, (5, 0.1))
        pool.execute()

    @timeout(3)
    def test_master_loop(self):
        pool = JobPool(network)
        job = pool.queue(test_dud, (5, 0.1))
        executed = False

        def spy_loop(p):
            nonlocal executed
            executed = True

        pool.execute(master_event_loop=spy_loop)
        if MPI.COMM_WORLD.Get_rank():
            self.assertFalse(executed, "workers executed master loop")
        else:
            self.assertTrue(executed, "master loop skipped")

    @timeout(3)
    def test_fake_futures(self):
        pool = JobPool(network)
        job = pool.queue(test_dud, (5, 0.1))
        self.assertIs(FakeFuture.done, job._future.done.__func__)
        self.assertFalse(job._future.done())
        self.assertFalse(job._future.running())

    @timeout(3)
    def test_dependencies(self):
        pool = JobPool(network)
        job = pool.queue(test_dud, (5, 0.1))
        job2 = pool.queue(test_dud, (5, 0.1), deps=[job])
        result = None

        def spy_queue(jobs):
            nonlocal result
            if result is None:
                result = jobs[0]._future.running() and not jobs[1]._future.running()

        pool.execute(master_event_loop=spy_queue)
        if not MPI.COMM_WORLD.Get_rank():
            self.assertTrue(result, "A job with unfinished dependencies was scheduled.")


@unittest.skipIf(MPI.COMM_WORLD.Get_size() > 1, "Skipped during parallel testing.")
class TestSerialScheduler(unittest.TestCase, SchedulerBaseTest):
    pass


class TestPlacementStrategies(unittest.TestCase):
    pass
