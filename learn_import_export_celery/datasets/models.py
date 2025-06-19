from django.db import models
from jsonschema.exceptions import ValidationError
from datetime import date


class Author(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Book(models.Model):
    name = models.CharField('Book name', max_length=100)
    author = models.ForeignKey(Author, blank=True, null=True, on_delete=models.CASCADE )
    author_email = models.EmailField('Author email', max_length=50, blank=True)
    imported = models.BooleanField(default=False)
    published = models.DateField('Published', blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    categories = models.ManyToManyField(Category, blank=True)

    def __str__(self):
        return self.name

    def full_clean(self, exclude=None, validate_unique=True, validation_constraints=False):
        super().full_clean(exclude, validate_unique)
        # not field specific validation
        if self.published < date(1900, 1,1):
            raise ValidationError("book is out of print")
        # field specific validation
        if self.name == "Ulysses":
            raise ValidationError({"name": "book has been banned"})
