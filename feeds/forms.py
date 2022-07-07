from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from feeds.models import Category, Subscription


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]


class SubscriptionCreateForm(forms.ModelForm):
    url = forms.URLField(label="URL")

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(user=user)

    class Meta:
        model = Subscription
        fields = ["url", "category"]


class SignUpForm(UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        if User.objects.filter(email=self.cleaned_data["email"]).exists():
            raise forms.ValidationError("the given email is already registered")
        return self.cleaned_data["email"]
