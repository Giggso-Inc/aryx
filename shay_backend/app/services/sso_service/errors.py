"""SSO exception hierarchy — stable error codes returned to API callers."""


class SSOError(Exception):
    def __init__(self, message: str, error_code: str):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class InvitationNotFoundError(SSOError):
    def __init__(self):
        super().__init__("Invitation not found", "SSO_005")


class InvitationInvalidError(SSOError):
    def __init__(self):
        super().__init__("Invitation has expired or already been used", "SSO_006")


class SignupInviteRequiredError(SSOError):
    """New SSO users must start from an invitation; returning users omit invite_id."""

    def __init__(self):
        super().__init__(
            "SSO sign-up requires a valid invite_id; for sign-in, omit invite_id if you already have an account",
            "SSO_012",
        )


class EmailMismatchError(SSOError):
    def __init__(self, provider: str):
        super().__init__(
            f"The email from your {provider} account does not match the invitation email",
            "SSO_007",
        )


class ProviderError(SSOError):
    def __init__(self, provider: str):
        super().__init__(f"Failed to authenticate with {provider}", "SSO_008")
