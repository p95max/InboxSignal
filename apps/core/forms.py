from django import forms


class ContactForm(forms.Form):
    """Public contact form."""

    name = forms.CharField(
        label="Name",
        max_length=120,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Your name",
                "autocomplete": "name",
            }
        ),
    )
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "you@example.com",
                "autocomplete": "email",
            }
        ),
    )
    subject = forms.CharField(
        label="Subject",
        max_length=160,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "How can we help?",
            }
        ),
    )
    message = forms.CharField(
        label="Message",
        max_length=3000,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Describe your issue or request...",
                "rows": 6,
            }
        ),
    )

    # Simple honeypot field. Humans do not see it, bots often fill it.
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )

    def clean_website(self):
        value = self.cleaned_data.get("website")

        if value:
            raise forms.ValidationError("Invalid form submission.")

        return value