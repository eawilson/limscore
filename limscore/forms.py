from .i18n import _
from .lib.forms import (Form,
                        Input,
                        TextInput,
                        TextAreaInput,
                        HiddenInput,
                        PasswordInput,
                        NameInput,
                        TextNumberInput,
                        LowerCaseInput,
                        EmailInput,
                        IntegerInput,
                        DecimalInput,
                        NHSNumberInput,
                        DateInput,
                        PastDateInput,
                        BooleanInput,
                        SelectInput,
                        MultiSelectInput,
                        MultiCheckboxInput,
                        FileInput,
                        DirectoryInput)



class TwoFactorForm(Form):
    def definition(self):
        self.secret = HiddenInput()



class LoginForm(Form):
    def definition(self):
        self.email = EmailInput(_("Email"))
        self.password = PasswordInput(_("Password"))
        self.authenticator = IntegerInput(_("Authenticator Code"))
        self.timezone = HiddenInput("", required=False)



class ChangePasswordForm(Form):
    def definition(self):        
        self.old_password = PasswordInput(_("Old Password"), autocomplete="new-password")
        self.password1 = PasswordInput(_("New Password"), autocomplete="new-password")
        self.password2 = PasswordInput(_("New Password"), autocomplete="new-password")

    def validate(self):
        if super().validate() and self.password1.data != self.password2.data:
            self.password1.errors = _("Passwords must match.")
        return not self.errors


    
class UserForm(Form):
    def definition(self):
        self.surname = TextInput(_("Surname"))
        self.forename = TextInput(_("Forename"))        
        self.email = EmailInput(_("Email"))
        self.groups = MultiCheckboxInput(_("Groups"), required=False)
        self.sites = MultiCheckboxInput(_("Sites"), required=False)
        self.restricted = BooleanInput(_("Restrict Projects"), details=_("Only allow access to selected projects."), required=False)        
        self.projects = MultiCheckboxInput(_("Projects"), required=False)



class ReorderForm(Form):
    def definition(self):
        self.order = HiddenInput(required=False)
            

