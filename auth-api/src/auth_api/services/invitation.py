# Copyright © 2019 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Service for managing Invitation data."""
from datetime import datetime
from typing import Dict

from flask import current_app
from itsdangerous import URLSafeTimedSerializer
from jinja2 import Environment, FileSystemLoader
from sbc_common_components.tracing.service_tracing import ServiceTracing  # noqa: I001

from auth_api.config import get_named_config
from auth_api.exceptions import BusinessException
from auth_api.exceptions.errors import Error
from auth_api.models import AccountLoginOptions as AccountLoginOptionsModel
from auth_api.models import Invitation as InvitationModel
from auth_api.models import InvitationStatus as InvitationStatusModel
from auth_api.models import Membership as MembershipModel
from auth_api.models.org import Org as OrgModel
from auth_api.schemas import InvitationSchema
from auth_api.services.user import User as UserService
from auth_api.utils.constants import GROUP_GOV_ACCOUNT_USERS
from auth_api.utils.enums import AccessType, InvitationStatus, InvitationType, LoginSource
from auth_api.utils.enums import OrgStatus as OrgStatusEnum
from auth_api.utils.enums import Status
from auth_api.utils.roles import ADMIN, COORDINATOR, STAFF, USER
from auth_api.utils.user_context import UserContext, user_context

from ..utils.account_mailer import publish_to_mailer
from ..utils.util import escape_wam_friendly_url
from .authorization import check_auth
from .keycloak import KeycloakService
from .membership import Membership as MembershipService


ENV = Environment(loader=FileSystemLoader('.'), autoescape=True)
CONFIG = get_named_config()


class Invitation:
    """Manages Invitation data.

    This service manages creating, updating, and retrieving Invitation data via the Invitation model.
    """

    def __init__(self, model):
        """Return an invitation service instance."""
        self._model = model

    @ServiceTracing.disable_tracing
    def as_dict(self):
        """Return the internal Invitation model as a dictionary."""
        invitation_schema = InvitationSchema()
        obj = invitation_schema.dump(self._model, many=False)
        return obj

    @staticmethod
    @user_context
    def create_invitation(invitation_info: Dict, user, invitation_origin, **kwargs):  # pylint: disable=too-many-locals
        """Create a new invitation."""
        user_from_context: UserContext = kwargs['user_context']
        # Ensure that the current user is ADMIN or COORDINATOR on each org being invited to
        context_path = CONFIG.AUTH_WEB_TOKEN_CONFIRM_PATH
        org_id = invitation_info['membership'][0]['orgId']
        # get the org and check the access_type
        org: OrgModel = OrgModel.find_by_org_id(org_id)
        if not org:
            raise BusinessException(Error.DATA_NOT_FOUND, None)

        check_auth(org_id=org_id, one_of_roles=(ADMIN, COORDINATOR, STAFF))

        org_name = org.name
        invitation_type = Invitation._get_inv_type(org)

        if org.access_type == AccessType.ANONYMOUS.value:  # anonymous account never get bceid or bcsc choices
            mandatory_login_source = LoginSource.BCROS.value
        elif org.access_type == AccessType.GOVM.value:
            mandatory_login_source = LoginSource.STAFF.value
        else:
            default_login_option_based_on_accesstype = LoginSource.BCSC.value if \
                org.access_type == AccessType.REGULAR.value else LoginSource.BCEID.value
            role = invitation_info['membership'][0]['membershipType']
            account_login_options = AccountLoginOptionsModel.find_active_by_org_id(org.id)
            mandatory_login_source = LoginSource.BCSC.value if \
                role == ADMIN else getattr(account_login_options, 'login_source',
                                           default_login_option_based_on_accesstype)

        invitation = InvitationModel.create_from_dict(invitation_info, user.identifier, invitation_type)
        confirmation_token = Invitation.generate_confirmation_token(invitation.id, invitation.type)
        invitation.token = confirmation_token
        invitation.login_source = mandatory_login_source
        invitation.save()
        Invitation.send_invitation(invitation, org_name, org.id, user.as_dict(),
                                   '{}/{}'.format(invitation_origin, context_path), mandatory_login_source,
                                   org_status=org.status_code)
        # notify admin if staff adds team members
        if user_from_context.is_staff() and invitation_type == InvitationType.STANDARD.value:
            try:
                current_app.logger.debug('<send_team_member_invitation_notification')
                publish_to_mailer(notification_type='teamMemberInvited', org_id=org_id)
                current_app.logger.debug('send_team_member_invitation_notification>')
            except Exception as e:  # noqa=B901
                current_app.logger.error('<send_team_member_invitation_notification failed')
                raise BusinessException(Error.FAILED_NOTIFICATION, None) from e
        return Invitation(invitation)

    @staticmethod
    def _get_inv_type(org):
        """Return the correct invitation type."""
        inv_types = {
            AccessType.GOVM.value: InvitationType.GOVM.value,
            AccessType.ANONYMOUS.value: InvitationType.DIRECTOR_SEARCH.value,
            AccessType.REGULAR.value: InvitationType.STANDARD.value
        }
        return inv_types.get(org.access_type, InvitationType.STANDARD.value)

    def update_invitation(self, user, invitation_origin):
        """Update the specified invitation with new data."""
        # Ensure that the current user is ADMIN or COORDINATOR on each org being re-invited to
        context_path = CONFIG.AUTH_WEB_TOKEN_CONFIRM_PATH
        for membership in self._model.membership:
            org_id = membership.org_id
            check_auth(org_id=org_id, one_of_roles=(ADMIN, COORDINATOR, STAFF))

        # TODO doesnt work when invited to multiple teams.. Re-work the logic when multiple teams introduced
        confirmation_token = Invitation.generate_confirmation_token(self._model.id, self._model.type)
        self._model.token = confirmation_token
        updated_invitation = self._model.update_invitation_as_retried()
        org_name = OrgModel.find_by_org_id(self._model.membership[0].org_id).name
        Invitation.send_invitation(updated_invitation, org_name, self._model.membership[0].org_id, user.as_dict(),
                                   '{}/{}'.format(invitation_origin, context_path), self._model.login_source)
        return Invitation(updated_invitation)

    @staticmethod
    def delete_invitation(invitation_id):
        """Delete the specified invitation."""
        # Ensure that the current user is ADMIN or COORDINATOR for each org in the invitation
        invitation = InvitationModel.find_invitation_by_id(invitation_id)
        if invitation is None:
            raise BusinessException(Error.DATA_NOT_FOUND, None)
        for membership in invitation.membership:
            org_id = membership.org_id
            check_auth(org_id=org_id, one_of_roles=(ADMIN, COORDINATOR, STAFF))
        invitation.delete()

    @staticmethod
    @user_context
    def get_invitations_for_org(org_id, status=None, **kwargs):
        """Get invitations for an org."""
        user_from_context: UserContext = kwargs['user_context']
        org_model = OrgModel.find_by_org_id(org_id)
        if not org_model:
            return None

        if status:
            status = InvitationStatus[status]

        # If staff return full list
        if user_from_context.is_staff():
            return InvitationModel.find_pending_invitations_by_org(org_id)

        current_user: UserService = UserService.find_by_jwt_token()
        current_user_membership: MembershipModel = \
            MembershipModel.find_membership_by_user_and_org(user_id=current_user.identifier, org_id=org_id)

        # If no active membership return empty array
        if current_user_membership is None or \
                current_user_membership.status != Status.ACTIVE.value:
            return []

        # Ensure either ADMIN or COORDINATOR
        if current_user_membership.membership_type_code == USER:
            return []

        return InvitationModel.find_invitations_by_org(org_id=org_id, status=status)

    @staticmethod
    def find_invitation_by_id(invitation_id):
        """Find an existing invitation with the provided id."""
        if invitation_id is None:
            return None

        invitation = InvitationModel.find_invitation_by_id(invitation_id)
        if not invitation:
            return None

        # Ensure that the current user is an ADMIN or COORDINATOR on each org in the invite being retrieved
        for membership in invitation.membership:
            org_id = membership.org_id
            check_auth(org_id=org_id, one_of_roles=(ADMIN, COORDINATOR, STAFF))

        return Invitation(invitation)

    @staticmethod
    def send_admin_notification(user, url, recipient_email_list, org_name, org_id):
        """Send the admin email notification."""
        data = {
            'accountId': org_id,
            'emailAddresses': recipient_email_list,
            'contextUrl': url,
            'userFirstName': user['firstname'],
            'userLastName': user['lastname'],
            'orgName': org_name
        }
        try:
            current_app.logger.debug('<send_admin_notification')
            publish_to_mailer(notification_type='adminNotification', org_id=org_id, data=data)
            current_app.logger.debug('send_admin_notification>')
        except Exception as e:  # noqa=B901
            current_app.logger.error('<send_admin_notification failed')
            raise BusinessException(Error.FAILED_NOTIFICATION, None) from e

    @staticmethod
    def send_invitation(invitation: InvitationModel, org_name, org_id, user,  # pylint: disable=too-many-arguments
                        app_url, login_source, org_status=None):
        """Send the email notification."""
        current_app.logger.debug('<send_invitation')
        mail_configs = Invitation._get_invitation_configs(org_name, login_source, org_status)
        recipient = invitation.recipient_email
        token_confirm_url = '{}/{}/{}'.format(app_url, mail_configs.get('token_confirm_path'), invitation.token)
        role = invitation.membership[0].membership_type.display_name
        data = {
            'accountId': org_id,
            'emailAddresses': recipient,
            'contextUrl': token_confirm_url,
            'userFirstName': user['firstname'],
            'userLastName': user['lastname'],
            'orgName': org_name,
            'role': role
        }

        try:
            publish_to_mailer(notification_type=mail_configs.get('notification_type'), org_id=org_id, data=data)
        except BusinessException as exception:
            invitation.invitation_status_code = 'FAILED'
            invitation.save()
            current_app.logger.debug('>send_invitation failed')
            current_app.logger.debug(exception)
            raise BusinessException(Error.FAILED_INVITATION, None) from exception

        current_app.logger.debug('>send_invitation')

    @staticmethod
    def _get_invitation_configs(org_name, login_source, org_status=None):
        """Get the config for different email types."""
        login_source = login_source or LoginSource.BCSC.value
        escape_url = escape_wam_friendly_url(org_name)
        token_confirm_path = f'{escape_url}/validatetoken/{login_source}'
        if login_source == LoginSource.STAFF.value:
            # for GOVM accounts , there are two kinda of invitation. Its same login source
            # if its first invitation to org , its an account set up invitation else normal joining invite
            login_source = 'IDIR/ACCOUNTSETUP' if Invitation._is_first_user_to_a_gov_accnt(org_status) else login_source

        govm_setup_configs = {
            'token_confirm_path': token_confirm_path,
            'notification_type': 'govmBusinessInvitation',
        }
        govm_member_configs = {
            'token_confirm_path': token_confirm_path,
            'notification_type': 'govmMemberInvitation',
        }
        director_search_configs = {
            'token_confirm_path': token_confirm_path,
            'notification_type': 'dirsearchBusinessInvitation',
        }
        bceid_configs = {
            'token_confirm_path': token_confirm_path,
            'notification_type': 'businessInvitationForBceid',
        }
        default_configs = {
            'token_confirm_path': token_confirm_path,
            'notification_type': 'businessInvitation',
        }
        mail_configs = {
            'BCROS': director_search_configs,
            'BCEID': bceid_configs,
            'IDIR': govm_member_configs,
            'IDIR/ACCOUNTSETUP': govm_setup_configs

        }
        return mail_configs.get(login_source, default_configs)

    @staticmethod
    def generate_confirmation_token(invitation_id, invitation_type=''):
        """Generate the token to be sent in the email."""
        serializer = URLSafeTimedSerializer(CONFIG.EMAIL_TOKEN_SECRET_KEY)
        token = {'id': invitation_id, 'type': invitation_type}
        return serializer.dumps(token, salt=CONFIG.EMAIL_SECURITY_PASSWORD_SALT)

    @staticmethod
    def _is_first_user_to_a_gov_accnt(org_status: str) -> bool:
        return org_status == OrgStatusEnum.PENDING_INVITE_ACCEPT.value

    @staticmethod
    def validate_token(token):
        """Check whether the passed token is valid."""
        serializer = URLSafeTimedSerializer(CONFIG.EMAIL_TOKEN_SECRET_KEY)
        token_valid_for = int(CONFIG.TOKEN_EXPIRY_PERIOD) * 3600 * 24 if CONFIG.TOKEN_EXPIRY_PERIOD else 3600 * 24 * 7
        try:
            invitation_id = serializer.loads(token, salt=CONFIG.EMAIL_SECURITY_PASSWORD_SALT,
                                             max_age=token_valid_for).get('id')
        except Exception as e:  # noqa: E722
            raise BusinessException(Error.EXPIRED_INVITATION, None) from e

        invitation: InvitationModel = InvitationModel.find_invitation_by_id(invitation_id)

        if invitation is None:
            raise BusinessException(Error.DATA_NOT_FOUND, None)
        if invitation.invitation_status_code == 'ACCEPTED':
            raise BusinessException(Error.ACTIONED_INVITATION, None)
        if invitation.invitation_status_code == 'EXPIRED':
            raise BusinessException(Error.EXPIRED_INVITATION, None)

        return Invitation(invitation)

    @staticmethod
    def notify_admin(user, invitation_id, membership_id, invitation_origin):
        """Admins should be notified if user has responded to invitation."""
        current_app.logger.debug('<notify_admin')
        admin_list = UserService.get_admins_for_membership(membership_id)
        invitation: InvitationModel = InvitationModel.find_invitation_by_id(invitation_id)
        context_path = CONFIG.AUTH_WEB_TOKEN_CONFIRM_PATH

        # Don't send email in case no admin exist in the org. (staff sent invitation)
        if len(admin_list) >= 1:
            admin_emails = ','.join([str(x.contacts[0].contact.email) for x in admin_list if x.contacts])
        else:
            # No admin, find Sender email to notify sender (staff)
            admin_emails = invitation.sender.email

        if admin_emails != '':
            Invitation.send_admin_notification(user.as_dict(),
                                               '{}/{}'.format(invitation_origin, context_path),
                                               admin_emails, invitation.membership[0].org.name,
                                               invitation.membership[0].org.id)
            current_app.logger.debug('>notify_admin')

        return Invitation(invitation)

    @staticmethod
    @user_context
    def accept_invitation(invitation_id, user: UserService, origin, add_membership: bool = True, **kwargs):
        """Add user, role and org from the invitation to membership."""
        current_app.logger.debug('>accept_invitation')
        user_from_context: UserContext = kwargs['user_context']
        invitation: InvitationModel = InvitationModel.find_invitation_by_id(invitation_id)

        if invitation is None:
            raise BusinessException(Error.DATA_NOT_FOUND, None)
        if invitation.invitation_status_code == 'ACCEPTED':
            raise BusinessException(Error.ACTIONED_INVITATION, None)
        if invitation.invitation_status_code == 'EXPIRED':
            raise BusinessException(Error.EXPIRED_INVITATION, None)

        if (login_source := user_from_context.login_source) is not None:  # bcros comes with out token
            if invitation.login_source != login_source:
                raise BusinessException(Error.INVALID_USER_CREDENTIALS, None)

        if add_membership:
            for membership in invitation.membership:
                membership_model = MembershipModel()
                membership_model.org_id = membership.org_id
                membership_model.user_id = user.identifier
                membership_model.membership_type = membership.membership_type

                # check to ensure an invitation for this user/org has not already been processed
                existing_membership = MembershipService \
                    .get_membership_for_org_and_user(org_id=membership_model.org_id, user_id=membership_model.user_id)

                if existing_membership:
                    raise BusinessException(Error.DATA_ALREADY_EXISTS, None)
                org_model: OrgModel = OrgModel.find_by_org_id(membership.org_id)

                # GOVM users gets direct approval since they are IDIR users.
                membership_model.status = Invitation._get_status_based_on_org(org_model)
                membership_model.save()
                try:
                    # skip notifying admin if it auto approved
                    # for now , auto approval happens for GOVM.If more auto approval comes , just check if its GOVM
                    if membership_model.status != Status.ACTIVE.value:
                        Invitation.notify_admin(user, invitation_id, membership_model.id, origin)
                except BusinessException as exception:
                    current_app.logger.error('<send_notification_to_admin failed', exception.message)
        invitation.accepted_date = datetime.now()
        invitation.invitation_status = InvitationStatusModel.get_status_by_code('ACCEPTED')
        invitation.save()

        # Call keycloak to add the user to the group.
        if user:
            group_name: str = KeycloakService.join_users_group()
            KeycloakService.join_account_holders_group(user.keycloak_guid)

            if group_name == GROUP_GOV_ACCOUNT_USERS:
                # Add contact to the user.
                user.add_contact(dict(email=user_from_context.token_info.get('email', None)),
                                 throw_error_for_duplicates=False)

        current_app.logger.debug('<accept_invitation')
        return Invitation(invitation)

    @staticmethod
    def _get_status_based_on_org(org_model: OrgModel):
        if org_model.access_type == AccessType.GOVM.value:
            return Status.ACTIVE.value
        return Status.PENDING_APPROVAL.value
