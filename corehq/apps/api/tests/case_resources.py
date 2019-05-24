from __future__ import absolute_import, unicode_literals

import json
import uuid
from datetime import datetime

from casexml.apps.case.mock import CaseBlock
from casexml.apps.case.models import CommCareCase
from dimagi.utils.parsing import json_format_datetime

from corehq.apps.api.models import ESCase
from corehq.apps.api.resources import v0_4, v0_3
from corehq.apps.domain.models import Domain
from corehq.apps.hqcase.utils import submit_case_blocks
from corehq.apps.users.models import WebUser
from corehq.form_processor.tests.utils import run_with_all_backends
from corehq.pillows.case import transform_case_for_elasticsearch
from custom.hope.models import CC_BIHAR_PREGNANCY

from .utils import APIResourceTest, FakeXFormES


class TestCommCareCaseResource(APIResourceTest):
    """
    Tests the CommCareCaseREsource, currently only v0_4
    """
    resource = v0_4.CommCareCaseResource

    def test_get_list(self):
        """
        Any case in the appropriate domain should be in the list from the API.
        """

        # The actual infrastructure involves saving to CouchDB, having PillowTop
        # read the changes and write it to ElasticSearch.

        # the pillow is set to offline mode - elasticsearch not needed to validate
        fake_case_es = FakeXFormES()
        v0_3.MOCK_CASE_ES = fake_case_es

        modify_date = datetime.utcnow()

        backend_case = CommCareCase(server_modified_on=modify_date, domain=self.domain.name)
        backend_case.save()
        self.addCleanup(backend_case.delete)

        translated_doc = transform_case_for_elasticsearch(backend_case.to_json())

        fake_case_es.add_doc(translated_doc['_id'], translated_doc)

        response = self._assert_auth_get_resource(self.list_endpoint)
        self.assertEqual(response.status_code, 200)

        api_cases = json.loads(response.content)['objects']
        self.assertEqual(len(api_cases), 1)

        api_case = api_cases[0]
        self.assertEqual(api_case['server_date_modified'], json_format_datetime(backend_case.server_modified_on))

    @run_with_all_backends
    def test_parent_and_child_cases(self):
        fake_case_es = FakeXFormES(ESCase)
        v0_3.MOCK_CASE_ES = fake_case_es

        # Create cases
        parent_case_id = uuid.uuid4().hex
        parent_type = 'parent_case_type'
        parent_case = submit_case_blocks(
            CaseBlock(
                case_id=parent_case_id,
                create=True,
                case_type=parent_type,
            ).as_string().decode('utf-8'),
            self.domain.name
        )[1][0]
        child_case_id = uuid.uuid4().hex
        child_case = submit_case_blocks(
            CaseBlock(
                case_id=child_case_id,
                create=True,
                index={'parent': (parent_type, parent_case_id)}
            ).as_string().decode('utf-8'),
            self.domain.name
        )[1][0]

        fake_case_es.add_doc(parent_case_id, transform_case_for_elasticsearch(parent_case.to_json()))
        fake_case_es.add_doc(child_case_id, transform_case_for_elasticsearch(child_case.to_json()))

        # Fetch the child case through the API

        response = self._assert_auth_get_resource(self.single_endpoint(child_case_id) + "?parent_cases__full=true")
        self.assertEqual(
            response.status_code,
            200,
            "Status code was not 200. Response content was {}".format(response.content)
        )
        parent_cases = list(json.loads(response.content)['parent_cases'].values())

        # Confirm that the case appears in the resource
        self.assertEqual(len(parent_cases), 1)
        self.assertEqual(parent_cases[0]['id'], parent_case_id)

        # Fetch the parent case through the API

        response = self._assert_auth_get_resource(self.single_endpoint(parent_case_id) + "?child_cases__full=true")
        self.assertEqual(
            response.status_code,
            200,
            "Status code was not 200. Response content was {}".format(response.content)
        )
        child_cases = list(json.loads(response.content)['child_cases'].values())

        # Confirm that the case appears in the resource
        self.assertEqual(len(child_cases), 1)
        self.assertEqual(child_cases[0]['id'], child_case_id)

    def test_no_subscription(self):
        """
        Tests authorization function properly blocks domains without proper subscription
        :return:
        """
        community_domain = Domain.get_or_create_with_name('dvorak', is_active=True)
        new_user = WebUser.create(community_domain.name, 'test', 'testpass')
        new_user.save()

        self.addCleanup(new_user.delete)
        self.addCleanup(community_domain.delete)

        response = self._assert_auth_get_resource(self.list_endpoint, username='test', password='testpass')
        self.assertEqual(response.status_code, 403)

    def test_superuser(self):
        """
        Tests superuser overrides authorization
        :return:
        """
        community_domain = Domain.get_or_create_with_name('dvorak', is_active=True)
        new_user = WebUser.create(community_domain.name, 'test', 'testpass', is_superuser=True)
        new_user.save()

        self.addCleanup(new_user.delete)
        self.addCleanup(community_domain.delete)

        response = self._assert_auth_get_resource(self.list_endpoint, username='test', password='testpass')
        self.assertEqual(response.status_code, 200)


class TestHOPECaseResource(APIResourceTest):
    """
    Tests the HOPECaseREsource, currently only v0_4, just to make sure
    it does not crash right away
    """
    resource = v0_4.HOPECaseResource

    def test_get_list(self):
        """
        Any case in the appropriate domain should be in the list from the API.
        """

        # The actual infrastructure involves saving to CouchDB, having PillowTop
        # read the changes and write it to ElasticSearch.

        fake_case_es = FakeXFormES()
        v0_3.MOCK_CASE_ES = fake_case_es

        modify_date = datetime.utcnow()

        backend_case = CommCareCase(server_modified_on=modify_date, domain=self.domain.name)
        backend_case.type = CC_BIHAR_PREGNANCY
        backend_case.save()
        self.addCleanup(backend_case.delete)

        translated_doc = transform_case_for_elasticsearch(backend_case.to_json())

        fake_case_es.add_doc(translated_doc['_id'], translated_doc)

        response = self._assert_auth_get_resource(self.list_endpoint)
        self.assertEqual(response.status_code, 200)

        api_cases = json.loads(response.content)['objects']
        self.assertEqual(len(api_cases), 2)

        api_case = api_cases['mother_lists'][0]
        self.assertEqual(api_case['id'], backend_case.case_id)
