from dcim.choices import CableProfileChoices
from dcim.models import *
from dcim.svg import CableTraceSVG
from dcim.tests.utils import BaseCablePathTestCase


class MPOPanelCablePathTestCase(BaseCablePathTestCase):
    """
    Reproduction of the topology reported in the comments of #23490:

    [Switch A IF1] --LC-- [FP1(p=2)] [RP1(p=12)] --MPO-- [RP1(p=12)] [FP1(p=2)] --LC-- [Switch B IF1]
    [Switch A IF2] --LC-- [FP7(p=2)] [RP2(p=12)] --MPO-- [RP2(p=12)] [FP7(p=2)] --LC-- [Switch B IF2]
                          Panel A                        Panel B

    Each panel has 12 duplex LC front ports (2 positions each) mapped onto two 12-position MPO rear
    ports: FP1-FP6 -> RP1 positions 1-12, FP7-FP12 -> RP2 positions 1-12.

    The report doesn't say which cable profiles were used, so each combination is tested.
    """

    def _create_device(self, name):
        return Device.objects.create(
            site=self.site,
            device_type=self.device.device_type,
            role=self.device.role,
            name=name,
        )

    def _create_panel(self, name):
        panel = self._create_device(name)
        rear_ports = [
            RearPort.objects.create(device=panel, name=f'MPO {i}', positions=12) for i in (1, 2)
        ]
        front_ports = [
            FrontPort.objects.create(device=panel, name=f'LC {i}', positions=2) for i in range(1, 13)
        ]
        mappings = []
        for i, front_port in enumerate(front_ports):
            rear_port = rear_ports[i // 6]
            for front_position in (1, 2):
                mappings.append(PortMapping(
                    device=panel,
                    front_port=front_port,
                    front_port_position=front_position,
                    rear_port=rear_port,
                    rear_port_position=(i % 6) * 2 + front_position,
                ))
        PortMapping.objects.bulk_create(mappings)
        return front_ports, rear_ports

    def _create_cable(self, a_terminations, b_terminations, profile=None):
        cable = Cable(profile=profile or '', a_terminations=a_terminations, b_terminations=b_terminations)
        cable.clean()
        cable.save()
        return cable

    def _build(self, lc_profile=None, mpo_profile=None, mpo_trunk=False):
        switch_a = self._create_device('Switch A')
        switch_b = self._create_device('Switch B')
        if_a = [Interface.objects.create(device=switch_a, name=f'Interface {i}') for i in (1, 2)]
        if_b = [Interface.objects.create(device=switch_b, name=f'Interface {i}') for i in (1, 2)]
        fp_a, rp_a = self._create_panel('Panel A')
        fp_b, rp_b = self._create_panel('Panel B')

        # MPO cabling between the panels
        if mpo_trunk:
            self._create_cable(rp_a, rp_b, profile=CableProfileChoices.TRUNK_2C12P)
        else:
            for rear_a, rear_b in zip(rp_a, rp_b):
                self._create_cable([rear_a], [rear_b], profile=mpo_profile)

        # LC patch cords from each switch to the panels (FP1 rides MPO 1, FP7 rides MPO 2)
        for interface, front_port in ((if_a[0], fp_a[0]), (if_a[1], fp_a[6])):
            self._create_cable([interface], [front_port], profile=lc_profile)
        for interface, front_port in ((if_b[0], fp_b[0]), (if_b[1], fp_b[6])):
            self._create_cable([interface], [front_port], profile=lc_profile)

        return if_a, if_b

    def _assert_end_to_end(self, if_a, if_b):
        for origin, destination in (
            (if_a[0], if_b[0]),
            (if_a[1], if_b[1]),
            (if_b[0], if_a[0]),
            (if_b[1], if_a[1]),
        ):
            with self.subTest(origin=f'{origin.device} {origin}'):
                origin.refresh_from_db()
                self.assertIsNotNone(origin._path_id, 'No path set')
                path = CablePath.objects.get(pk=origin._path_id)
                self.assertFalse(path.is_split, f'Path is split: {path.path_objects}')
                self.assertTrue(path.is_complete, f'Path is incomplete: {path.path_objects}')
                self.assertEqual(path.destinations, [destination])
                CableTraceSVG(origin).render()

    def test_lc_unprofiled_mpo_unprofiled(self):
        self._assert_end_to_end(*self._build())

    def test_lc_unprofiled_mpo_1c12p(self):
        self._assert_end_to_end(*self._build(mpo_profile=CableProfileChoices.SINGLE_1C12P))

    def test_lc_unprofiled_mpo_trunk_2c12p(self):
        self._assert_end_to_end(*self._build(mpo_trunk=True))

    def test_lc_1c2p_mpo_unprofiled(self):
        self._assert_end_to_end(*self._build(lc_profile=CableProfileChoices.SINGLE_1C2P))

    def test_lc_1c2p_mpo_1c12p(self):
        self._assert_end_to_end(*self._build(
            lc_profile=CableProfileChoices.SINGLE_1C2P,
            mpo_profile=CableProfileChoices.SINGLE_1C12P,
        ))

    def test_lc_1c2p_mpo_trunk_2c12p(self):
        self._assert_end_to_end(*self._build(lc_profile=CableProfileChoices.SINGLE_1C2P, mpo_trunk=True))
