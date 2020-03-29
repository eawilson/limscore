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



class LoginForm(Form):
    def definition(self):
        self.username = LowerCaseInput("Username or Email")
        self.password = PasswordInput("Password", required=False)
        self.timezone = HiddenInput()



class ChangePasswordForm(Form):
    def definition(self):        
        self.old_password = PasswordInput('Old Password', autocomplete="new-password")
        self.password1 = PasswordInput('New Password', autocomplete="new-password")
        self.password2 = PasswordInput('New Password', autocomplete="new-password")

    def validate(self):
        if super().validate() and self.password1.data != self.password2.data:
            self.password1.errors = "Passwords must match."
        return not self.errors


    
class UserForm(Form):
    def definition(self):
        self.username = LowerCaseInput("Username", autocomplete="new-password")
        self.surname = TextInput("Surname")
        self.forename = TextInput("Forename")        
        self.email = EmailInput("Email")
        self.password = PasswordInput('Password', autocomplete="new-password")
        self.group_id = MultiCheckboxInput("Groups", required="Every user must be a member of at least one group.")
        self.site_id = MultiCheckboxInput("Sites", required=False)
        self.restricted = BooleanInput("Restrict Projects", details="Only allow access to selected projects.", required=False)        
        self.project_id = MultiCheckboxInput("Projects", required=False)



class ReorderForm(Form):
    def definition(self):
        self.order = HiddenInput(required=False)
            

