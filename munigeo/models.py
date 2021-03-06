# -*- coding: utf-8 -*-

from django.utils.encoding import python_2_unicode_compatible

from django.contrib.gis.db import models
from django.db.models.query import QuerySet, Q
from django.conf import settings
from mptt.models import MPTTModel, TreeForeignKey
from mptt.managers import TreeManager

from django.utils.translation import ugettext as _

# If SRID not configured in settings, use the global Spherical
# Mercator projection.
if hasattr(settings, 'PROJECTION_SRID'):
    PROJECTION_SRID = settings.PROJECTION_SRID
else:
    PROJECTION_SRID = 3857


@python_2_unicode_compatible
class AdministrativeDivisionType(models.Model):
    type = models.CharField(max_length=60, unique=True, db_index=True,
                            help_text=_("Type name of the division (e.g. muni, school_district)"))
    name = models.CharField(max_length=100,
                            help_text=_("Human-readable name for the division"))
    ## European Union Nomenclature des Unités Territoriales Statistiques level
    #nuts_level = models.PositiveSmallIntegerField(null=True, db_index=True)
    ## European Union Local Administrative Unit level
    #lau_level = models.PositiveSmallIntegerField(null=True, db_index=True)

    def __str__(self):
        return "%s (%s)" % (self.name, self.type)


class AdministrativeDivisionQuerySet(QuerySet):

    def by_ancestor(self, ancestor):
        manager = self.model.objects
        max_level = manager.determine_max_level()
        qs = Q()
        # Construct an OR'd queryset for each level of parenthood.
        for i in range(max_level):
            key = '__'.join(['parent'] * (i + 1))
            qs |= Q(**{key: ancestor})
        return self.filter(qs)


class AdministrativeDivisionManager(TreeManager):

    def get_queryset(self):
        return AdministrativeDivisionQuerySet(self.model, using=self._db)

    def determine_max_level(self):
        if hasattr(self, '_max_level'):
            return self._max_level
        qs = self.all().order_by('-level')
        # FIXME: Use signals to catch new level being added
        if False and qs.count():
            self._max_level = qs[0].level
        else:
            # Harrison-Stetson method
            self._max_level = 6
        return self._max_level


@python_2_unicode_compatible
class AdministrativeDivision(MPTTModel):
    type = models.ForeignKey(AdministrativeDivisionType, db_index=True)
    name = models.CharField(max_length=100, null=True, db_index=True)
    parent = TreeForeignKey('self', db_index=True, null=True,
                            related_name='children')

    origin_id = models.CharField(max_length=50, db_index=True)
    ocd_id = models.CharField(max_length=200, unique=True, db_index=True, null=True,
                              help_text=_("Open Civic Data identifier"))

    municipality = models.ForeignKey('munigeo.Municipality', null=True)

    # Service districts might have a related service point id
    service_point_id = models.CharField(max_length=50, db_index=True, null=True,
                                        blank=True)

    # Some divisions might be only valid during some time period.
    # (E.g. yearly school districts in Helsinki)
    start = models.DateField(null=True)
    end = models.DateField(null=True)

    modified_at = models.DateTimeField(auto_now=True,
                                       help_text='Time when the information was last changed')

    objects = AdministrativeDivisionManager()

    def __str__(self):
        ocd_id = ''
        if self.ocd_id:
            ocd_id = '%s / ' % self.ocd_id
        return "%s (%s%s)" % (self.name, ocd_id, self.type.type)

    class Meta:
        unique_together = (('origin_id', 'type', 'parent'),)


class AdministrativeDivisionGeometry(models.Model):
    division = models.OneToOneField(AdministrativeDivision, related_name='geometry')
    boundary = models.MultiPolygonField(srid=PROJECTION_SRID)

    objects = models.GeoManager()


@python_2_unicode_compatible
class Municipality(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=100, null=True, db_index=True)
    division = models.ForeignKey(AdministrativeDivision, null=True, db_index=True,
                                 unique=True, related_name='muni')

    objects = models.Manager()

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class Plan(models.Model):
    municipality = models.ForeignKey(Municipality)
    geometry = models.MultiPolygonField(srid=PROJECTION_SRID)
    origin_id = models.CharField(max_length=20)
    in_effect = models.BooleanField(default=False)

    objects = models.GeoManager()

    def __str__(self):
        effect = "in effect"
        if not self.in_effect:
            effect = "not " + effect
        return "Plan %s (%s, %s)" % (self.origin_id, self.municipality, effect)

    class Meta:
        unique_together = (('municipality', 'origin_id'),)


@python_2_unicode_compatible
class Street(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    municipality = models.ForeignKey(Municipality, db_index=True)

    def __str__(self):
        return self.name

    class Meta:
        unique_together = (('municipality', 'name'),)


@python_2_unicode_compatible
class Address(models.Model):
    street = models.ForeignKey(Street, db_index=True, related_name='addresses')
    number = models.CharField(max_length=6, blank=True,
                              help_text="Building number")
    number_end = models.CharField(max_length=6, blank=True,
                                  help_text="Building number end (if range specified)")
    letter = models.CharField(max_length=2, blank=True,
                              help_text="Building letter if applicable")
    location = models.PointField(srid=PROJECTION_SRID,
                                 help_text="Coordinates of the address")

    objects = models.GeoManager()

    def __str__(self):
        s = '%s %s' % (self.street, self.number)
        if self.number_end:
            s += '-%s' % self.number_end
        if self.letter:
            s += '%s' % self.letter
        s += ', %s' % self.street.municipality
        return s

    class Meta:
        unique_together = (('street', 'number', 'number_end', 'letter'),)
        ordering = ['street', 'number']


@python_2_unicode_compatible
class POICategory(models.Model):
    type = models.CharField(max_length=50, db_index=True)
    description = models.CharField(max_length=100)

    def __str__(self):
        return "%s (%s)" % (self.type, self.description)


@python_2_unicode_compatible
class POI(models.Model):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(POICategory, db_index=True)
    description = models.TextField(null=True, blank=True)
    location = models.PointField(srid=PROJECTION_SRID)
    municipality = models.ForeignKey(Municipality, db_index=True)
    street_address = models.CharField(max_length=100, null=True, blank=True)
    zip_code = models.CharField(max_length=10, null=True, blank=True)
    origin_id = models.CharField(max_length=40, db_index=True, unique=True)

    objects = models.GeoManager()

    def __str__(self):
        return "%s (%s, %s)" % (self.name, self.category.type, self.municipality)
