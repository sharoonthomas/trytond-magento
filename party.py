# -*- coding: utf-8 -*-
import magento

from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import PoolMeta, Pool
from trytond.transaction import Transaction


__all__ = ['Party', 'MagentoWebsiteParty', 'Address']
__metaclass__ = PoolMeta


class Party:
    "Party"
    __name__ = 'party.party'

    magento_ids = fields.One2Many(
        "sale.channel.magento.party", "party", "Magento IDs", readonly=True
    )

    @classmethod
    def __setup__(cls):
        """
        Setup the class before adding to pool
        """
        super(Party, cls).__setup__()
        cls._error_messages.update({
            'channel_not_found': 'Website does not exist in context'
        })

    @classmethod
    def find_or_create_using_magento_id(cls, magento_id):
        """
        This method tries to find the party with the magento ID first and
        if not found it will fetch the info from magento and create a new
        party with the data from magento using create_using_magento_data

        :param magento_id: Party ID sent by magento
        :return: Active record of record created/found
        """
        Channel = Pool().get('sale.channel')

        channel = Channel.get_current_magento_channel()

        party = cls.find_using_magento_id(magento_id)
        if not party:
            with magento.Customer(
                channel.magento_url, channel.magento_api_user,
                channel.magento_api_key
            ) as customer_api:
                customer_data = customer_api.info(magento_id)

            party = cls.create_using_magento_data(customer_data)
        return party

    @classmethod
    def find_using_magento_id(cls, magento_id):
        """
        This method tries to find the party with the magento ID

        :param magento_id: Party ID sent by magento
        :return: Active record of record found
        """
        MagentoParty = Pool().get('sale.channel.magento.party')

        try:
            magento_party, = MagentoParty.search([
                ('magento_id', '=', magento_id),
                ('channel', '=', Transaction().context['current_channel'])
            ])
        except ValueError:
            return None
        else:
            return magento_party.party

    @classmethod
    def find_or_create_using_magento_data(cls, magento_data):
        """
        Looks for the customer whose magento_data is sent by magento against
        the magento_channel in context.
        If a record exists for this, return that else create a new one and
        return

        :param magento_data: Dictionary of values for customer sent by magento
        :return: Active record of record created/found
        """
        if Transaction().context.get('current_channel') is None:
            cls.raise_user_error('channel_not_found')

        party = cls.find_using_magento_data(magento_data)

        if not party:
            party = cls.create_using_magento_data(magento_data)

        return party

    @classmethod
    def create_using_magento_data(cls, magento_data):
        """
        Creates record of customer values sent by magento

        :param magento_data: Dictionary of values for customer sent by magento
        :return: Active record of record created
        """
        values = {
            'name': u' '.join(filter(
                None, [magento_data['firstname'], magento_data['lastname']]
            )),
            'magento_ids': [
                ('create', [{
                    'magento_id': magento_data['customer_id'],
                    'channel': Transaction().context['current_channel'],
                }])
            ],
        }
        if magento_data.get('email'):
            values.update({'contact_mechanisms': [
                ('create', [{
                    'type': 'email',
                    'value': magento_data['email'],
                }])
            ]})
        party, = cls.create([values])

        return party

    @classmethod
    def find_using_magento_data(cls, magento_data):
        """
        Looks for the customer whose magento_data is sent by magento against
        the magento_channel_id in context.
        If record exists returns that else None

        :param magento_data: Dictionary of values for customer sent by magento
        :return: Active record of record found or None
        """
        MagentoParty = Pool().get('sale.channel.magento.party')

        try:
            magento_party, = MagentoParty.search([
                ('magento_id', '=', magento_data['customer_id']),
                ('channel', '=', Transaction().context['current_channel'])
            ])
        except ValueError:
            return None
        else:
            return magento_party.party


class MagentoWebsiteParty(ModelSQL, ModelView):
    "Magento Website Party"
    __name__ = 'sale.channel.magento.party'

    magento_id = fields.Integer('Magento ID', readonly=True)
    channel = fields.Many2One(
        'sale.channel', 'Channel', required=True, readonly=True
    )
    party = fields.Many2One(
        'party.party', 'Party', required=True, readonly=True
    )

    @classmethod
    def validate(cls, records):
        super(MagentoWebsiteParty, cls).validate(records)
        cls.check_unique_party(records)

    @classmethod
    def __setup__(cls):
        """
        Setup the class before adding to pool
        """
        super(MagentoWebsiteParty, cls).__setup__()
        cls._error_messages.update({
            'party_exists': 'A party must be unique in a channel'
        })

    @classmethod
    def check_unique_party(cls, records):
        """Checks thats each party should be unique in a channel if it
        does not have a magento ID of 0. magento_id of 0 means its a guest
        customer.

        :param records: List of active records
        """
        for magento_partner in records:
            if magento_partner.magento_id != 0 and cls.search([
                ('magento_id', '=', magento_partner.magento_id),
                ('channel', '=', magento_partner.channel.id),
                ('id', '!=', magento_partner.id),
            ], count=True) > 0:
                cls.raise_user_error('party_exists')


class Address:
    "Address"
    __name__ = 'party.address'

    def match_with_magento_data(self, address_data):
        """
        Match the current address with the address_record.
        Match all the fields of the address, i.e., streets, city, subdivision
        and country. For any deviation in any field, returns False.

        :param address_data: Dictionary of address data from magento
        :return: True if address matches else False
        """
        Country = Pool().get('country.country')
        Subdivision = Pool().get('country.subdivision')

        # Check if the name matches
        if self.name != ' '.join(
            filter(None, [address_data['firstname'], address_data['lastname']])
        ):
            return False

        # Find country and subdivision based on magento data
        country = None
        subdivision = None
        if address_data['country_id']:
            country = Country.search_using_magento_code(
                address_data['country_id']
            )
            if address_data['region']:
                subdivision = Subdivision.search_using_magento_region(
                    address_data['region'], country
                )

        street, streetbis = self.get_street_parts(address_data['street'])

        if not all([
            self.street == (street or None),
            self.streetbis == (streetbis or None),
            self.zip == (address_data['postcode'] or None),
            self.city == (address_data['city'] or None),
            self.country == country,
            self.subdivision == subdivision,
        ]):
            return False

        return True

    @classmethod
    def get_street_parts(cls, magento_street_address):
        """
        Magento has only 1 street address column and a line separator
        puts that into two address lines.
        """
        street_parts = magento_street_address.split('\n', 1)
        if len(street_parts) == 2:
            return street_parts[0], street_parts[1]
        else:
            return magento_street_address, None

    @classmethod
    def find_or_create_for_party_using_magento_data(cls, party, address_data):
        """
        Look for the address in tryton corresponding to the address_record.
        If found, return the same else create a new one and return that.

        :param party: Party active record
        :param address_data: Dictionary of address data from magento
        :return: Active record of address created/found
        """
        for address in party.addresses:
            if address.match_with_magento_data(address_data):
                break

        else:
            address = cls.create_for_party_using_magento_data(
                party, address_data
            )

        return address

    @classmethod
    def create_for_party_using_magento_data(cls, party, address_data):
        """
        Create address from the address record given and link it to the
        party.

        :param party: Party active record
        :param address_data: Dictionary of address data from magento
        :return: Active record of created address
        """
        Country = Pool().get('country.country')
        Subdivision = Pool().get('country.subdivision')
        ContactMechanism = Pool().get('party.contact_mechanism')

        country = None
        subdivision = None
        if address_data['country_id']:
            country = Country.search_using_magento_code(
                address_data['country_id']
            )
            if address_data['region']:
                subdivision = Subdivision.search_using_magento_region(
                    address_data['region'], country
                )

        street, streetbis = cls.get_street_parts(address_data['street'])
        address, = cls.create([{
            'party': party.id,
            'name': ' '.join(filter(
                None, [address_data['firstname'], address_data['lastname']]
            )),
            'street': street,
            'streetbis': streetbis,
            'zip': address_data['postcode'],
            'city': address_data['city'],
            'country': country and country.id or None,
            'subdivision': subdivision and subdivision.id or None,
        }])

        # Create phone as contact mechanism
        if address_data.get('telephone') and not ContactMechanism.search([
            ('party', '=', party.id),
            ('type', 'in', ['phone', 'mobile']),
            ('value', '=', address_data['telephone']),
        ]):
            ContactMechanism.create([{
                'party': party.id,
                'type': 'phone',
                'value': address_data['telephone'],
            }])

        return address
