# Copyright © 2019 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the Affidavit service.

Test suite to ensure that the affidavit service routines are working as expected.
"""

from auth_api.services import Affidavit as AffidavitService
from auth_api.services import Org as OrgService
from auth_api.utils.enums import AffidavitStatus, LoginSource, OrgStatus
from tests.utilities.factory_scenarios import TestAffidavit, TestJwtClaims, TestOrgInfo
from tests.utilities.factory_utils import factory_user_model, factory_user_model_with_contact, patch_token_info


def test_create_affidavit(session, keycloak_mock, monkeypatch):  # pylint:disable=unused-argument
    """Assert that an Affidavit can be created."""
    user = factory_user_model()
    token_info = TestJwtClaims.get_test_real_user(user.keycloak_guid)
    patch_token_info(token_info, monkeypatch)
    affidavit_info = TestAffidavit.get_test_affidavit_with_contact()
    affidavit = AffidavitService.create_affidavit(affidavit_info=affidavit_info)

    assert affidavit
    assert affidavit.as_dict().get('status', None) == AffidavitStatus.PENDING.value


def test_create_affidavit_duplicate(session, keycloak_mock, monkeypatch):  # pylint:disable=unused-argument
    """Assert that duplicate Affidavit cannot be created."""
    user = factory_user_model()
    token_info = TestJwtClaims.get_test_real_user(user.keycloak_guid)
    patch_token_info(token_info, monkeypatch)

    affidavit_info = TestAffidavit.get_test_affidavit_with_contact()
    affidavit = AffidavitService.create_affidavit(affidavit_info=affidavit_info)

    assert affidavit.as_dict().get('status', None) == AffidavitStatus.PENDING.value
    new_affidavit_info = TestAffidavit.get_test_affidavit_with_contact()
    AffidavitService.create_affidavit(affidavit_info=new_affidavit_info)


def test_approve_org(session, keycloak_mock, monkeypatch):  # pylint:disable=unused-argument
    """Assert that an Affidavit can be approved."""
    user = factory_user_model_with_contact()
    token_info = TestJwtClaims.get_test_user(sub=user.keycloak_guid, source=LoginSource.BCEID.value)
    patch_token_info(token_info, monkeypatch)

    affidavit_info = TestAffidavit.get_test_affidavit_with_contact()
    AffidavitService.create_affidavit(affidavit_info=affidavit_info)
    org = OrgService.create_org(TestOrgInfo.org_with_mailing_address(), user_id=user.id)
    org_dict = org.as_dict()
    assert org_dict['org_status'] == OrgStatus.PENDING_STAFF_REVIEW.value
    org = OrgService.approve_or_reject(org_dict['id'], is_approved=True)
    org_dict = org.as_dict()
    assert org_dict['org_status'] == OrgStatus.ACTIVE.value
    affidavit = AffidavitService.find_affidavit_by_org_id(org_dict['id'])
    assert affidavit['status'] == AffidavitStatus.APPROVED.value


def test_reject_org(session, keycloak_mock, monkeypatch):  # pylint:disable=unused-argument
    """Assert that an Affidavit can be rejected."""
    user = factory_user_model_with_contact()
    token_info = TestJwtClaims.get_test_user(sub=user.keycloak_guid, source=LoginSource.BCEID.value)
    patch_token_info(token_info, monkeypatch)

    affidavit_info = TestAffidavit.get_test_affidavit_with_contact()
    AffidavitService.create_affidavit(affidavit_info=affidavit_info)
    org = OrgService.create_org(TestOrgInfo.org_with_mailing_address(), user_id=user.id)
    org_dict = org.as_dict()
    assert org_dict['org_status'] == OrgStatus.PENDING_STAFF_REVIEW.value
    org = OrgService.approve_or_reject(org_dict['id'], is_approved=False)
    org_dict = org.as_dict()
    assert org_dict['org_status'] == OrgStatus.REJECTED.value
    affidavit = AffidavitService.find_affidavit_by_org_id(org_dict['id'])
    assert affidavit['status'] == AffidavitStatus.REJECTED.value
