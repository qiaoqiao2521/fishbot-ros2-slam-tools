import unittest

from map_geometry import (
    DomainFormatError,
    decode_forbidden_zone,
    decode_virtual_wall,
    encode_forbidden_zone,
    encode_virtual_wall,
)


class GeometryTests(unittest.TestCase):
    def test_quadrilateral_round_trip(self):
        coords = [0, 0, 2, 1, 1, 3, -1, 2]
        self.assertEqual(encode_forbidden_zone(decode_forbidden_zone(coords)), coords)

    def test_wall_round_trip(self):
        coords = [-1, 0.5, 2, 3]
        self.assertEqual(encode_virtual_wall(decode_virtual_wall(coords)), coords)

    def test_bad_shapes_and_bool_are_rejected(self):
        for values in ([1, 2, 3], [True, 0, 1, 2]):
            with self.subTest(values=values), self.assertRaises(DomainFormatError):
                decode_virtual_wall(values)


if __name__ == '__main__':
    unittest.main()
