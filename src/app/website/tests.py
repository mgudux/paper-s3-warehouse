from django.test import TestCase
from django.utils import timezone

from .models import Device, Item


class SimpleHistory(TestCase):
    def setUp(self):
        self.device_1 = Device.objects.create(
            mac_address="Test MAC",
            row=1,
            bottom_level=1,
            left_box=1,
            height=2,
            width=2
        )
        self.item_1 = Item.objects.create(
            device=self.device_1,
            name="Test Item 1",
            stock=100,
            min_stock=10,
            row=1,
            level=1,
            box=1
        )
        self.t0 = timezone.now()

        self.item_2 = Item.objects.create(
            device=self.device_1,
            name="Test Item 2",
            stock=100,
            min_stock=10,
            row=1,
            level=1,
            box=1
        )
        self.t1 = timezone.now()

        self.device_1.mac_address = "New Test MAC"
        self.device_1.save()
        self.t2 = timezone.now()

    def test_history(self):
        # Check if only item_1 exists at timestamp 0
        items_at_t0 = Item.history.as_of(self.t0).filter(device=self.device_1)
        self.assertEqual(items_at_t0.count(), 1)
        self.assertEqual(items_at_t0[0].name, "Test Item 1")

        # Check if two items exists at timestamp 1
        items_at_t1 = Item.history.as_of(self.t1).filter(
            device=self.device_1).order_by('name')
        self.assertEqual(items_at_t1.count(), 2)
        self.assertEqual(items_at_t1[0].name, "Test Item 1")
        self.assertEqual(items_at_t1[1].name, "Test Item 2")

        # Check device mac_address at timestamp 0 (original value)
        device_asof_t0 = self.device_1.history.as_of(self.t0)
        self.assertEqual(device_asof_t0.mac_address, "Test MAC")

        # Check device mac_address at timestamp 2 (updated value)
        device_asof_t2 = self.device_1.history.as_of(self.t2)
        self.assertEqual(device_asof_t2.mac_address, "New Test MAC")
