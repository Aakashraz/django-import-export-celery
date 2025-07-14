import hashlib

from django import forms
from django.contrib import admin
from import_export import resources
from import_export.forms import ImportForm, ConfirmImportForm, ExportForm

from .models import Book, Author, Category
from import_export.fields import Field
from import_export.admin import ImportExportModelAdmin, ImportMixin
from import_export.widgets import DateWidget, IntegerWidget, ForeignKeyWidget, ManyToManyWidget


# for index, row_result in enumerate(result.rows):
# This row_result in above for loop: ---
# --- The row_result.__dict__ output is like looking at the internal 'medical record' of a failed row import,
# and it tells us a very specific story about what went wrong. The output is given below:
# {
#     'errors': [],                    # No general import errors
#     'validation_error': ValidationError({'published': ['Value could not be parsed using defined formats.']}),
#     'diff': None,                    # No diff because validation failed
#     'import_type': 'invalid',        # This row was marked as invalid
#     'row_values': {},               # Empty because validation failed early
#     'object_id': None,              # No database object was created
#     'object_repr': None,            # No object representation available
#     'instance': None,               # No Django model instance was created
#     'original': None                # No original object (this was meant to be new)
# }



class PositiveIntegerWidget(IntegerWidget):
    """Return a positive integer value"""
    def clean(self, value, row=None, **kwargs):
        val = super().clean(value, row=row, **kwargs)
        if val is not None and val < 0:
            raise ValueError("value must be positive")
        return val


class AuthorForeignKeyWidget(ForeignKeyWidget):
    """
    A ForeignKeyWidget for the Author model that handles two special cases:
    1. If an author name is not found in the database, it creates a new Author.
    2. If the author name is missing or empty in the imported file, it assigns
       a default Author with the name 'NA'.
    """
    model = Author
    field = 'name'
    # model = Author: This tells the ForeignKeyWidget that it's dealing
    # with a foreign key relationship to the Author model.
    #
    # field = 'name': This is the crucial part. It means that when django-import-export
    # encounters a value in the "Author" column of your import file, it will use that
    # value to try and find an existing Author record by matching it against the name field of the Author model.

    def __init__(self, publisher_id, **kwargs):
        super().__init__(self.model, field=self.field, **kwargs)
        self.publisher_id = publisher_id

    # Customize Relation lookup
    def get_queryset(self, value, row, *args, **kwargs):
        return self.model.objects.filter(publisher_id=self.publisher_id)


    def clean(self, value, row=None, **kwargs):
        # The value parameter holds the data from the cell (Author's column) in the imported file.
        # We first check if this value is empty, None, or otherwise "falsy".
        if not value:
            # If the value is missing, we'll use 'NA' as the author's name.
            # It fetches the Author named 'NA' if it already exists, or creates it if it doesn't,
            # all in a single database transaction.
            author_instance, created = Author.objects.get_or_create(name="NA")
            return author_instance

        # If a value exists, we proceed with the original logic.
        try:
            # 'super().clean(value)' will attempt to find the Author in the database using the provided value.
            return super().clean(value, row, **kwargs)
        except Author.DoesNotExist:
            return Author.objects.create(name=value)


class BookResource(resources.ModelResource):
    # If using the fields attribute to declare fields then
    # the declared resource attribute name must appear in the fields list
    published_field = Field(attribute='published', column_name='published_date',
                           widget=DateWidget(format='%Y-%m-%d'))
    price = Field(attribute='price', column_name='price', widget=PositiveIntegerWidget())
    hash_id = Field(column_name='hash_id', attribute=None)      # Define Dynamic Field, not stored in the model

    # author = Field(attribute='author',column_name='author',
    #                widget=AuthorForeignKeyWidget(Author, field='name'))
    # For Dynamically setting/accessing the author field with the publisher_id
    def __init__(self, publisher_id=None, author_id=None):
        super().__init__()
        # Store author_id for export filtering
        self.author_id = author_id

        self.fields["author"] = Field(
            attribute="author",
            column_name='author',
            widget=AuthorForeignKeyWidget(publisher_id),    # No use_natural_foreign_keys=True
            # Passes publisher_id to the AuthorForeignKeyWidget, enabling runtime customization.
        )

    # The filter_export method assumes Book.author is a ForeignKey to Author,
    # as it filters by author_id (the foreign key’s database column).
    def filter_export(self, queryset, **kwargs):
        # Apply author_id filter if provided
        if self.author_id:
            return queryset.filter(author_id=self.author_id)    # Filtered queryset (Dynamic Filtering)
        return queryset     # Unfiltered queryset

    # Using hash_id as dynamic unique identifier
    def before_import(self, dataset, **kwargs):
        print("Headers:", dataset.headers)
        print("Data:", dataset.dict)
        if 'hash_id' not in dataset.headers:
            dataset.headers.append("hash_id")
        super().before_import(dataset, **kwargs)

    def before_import_row(self, row, **kwargs):
        # To check if 'name' value exist.
        if 'name' not in row or not row['name']:
            raise ValueError("Row missing 'name' column or value.")
        row["hash_id"] = hashlib.sha256(row['name'].encode()).hexdigest()

    # By providing your own get_instance method, you are telling django-import-export:
    # "Stop. Don't use your default lookup logic. I will provide the exact instructions
    # to find the database object myself."
    def get_instance(self, instance_loader, row):
        # Override to return None prevents the library from trying to query the Book model for
        # hash_id (which doesn't exist).
        # return None   # Treat all rows as new or handle custom logic if needed.

        if 'name' not in row or not row['name']:
            return None

        # Find Book with matching name (since hash_id is derived from name)
        try:
            return self.Meta.model.objects.get(name=row['name'])
        except self.Meta.model.DoesNotExist:
            return None

    # This is implemented as a Model.objects.get() query, so if the instance in not uniquely identifiable based
    # on the given arg, then the import process will raise either DoesNotExist or MultipleObjectsReturned errors.
    # Example: The query Author.objects.get(name="J.K. Rowling") is needed during CSV import because
    # the Book.author field is a ForeignKey that requires an existing Author instance, not a string like "J.K. Rowling".

    categories = Field(attribute='categories', column_name='categories',
                       widget=ManyToManyWidget(Category, field='name', separator='|'))

    # This method runs for every row after it's saved.
    def after_import_row(self, row, row_result, **kwargs):
        # Consider checking for None values, which might lead to an error
        original = row_result.original
        instance = row_result.instance

        # if getattr(row_result.original, "published") is None \
        #     and getattr(row_result.instance, "published") is not None:
        # The above logic is replaced as:
        if original is not None and original.published is None \
            and instance is not None and instance.published is not None:
            # import value is different from stored value.
            # execute your custom logic here, like sending an email.
            print(f"Workflow triggered for books: {row_result.instance.name}")
            # send_new_release notification(row_result.instance)

        # Diagnostic information for troubleshooting
        elif instance is not None and hasattr(instance, 'published') and  instance.published is None:
            # The date field is None, which might indicate parsing failure or an empty field
            raw_date_value = row.get('published_field', 'NOT_FOUND')
            print(f"Warning: Date parsing may have failed for '{instance.name}'. Raw value:'{raw_date_value}'")

        else:
            # Log what we actually received for debugging
            print(f"Debug - Original: {original}, Instance: {instance}")
            if instance:
                print(f"Instance published: {getattr(instance, 'published', 'MISSING')}")

    def for_delete(self, row, instance):
        # Delete if 'delete' column has value '1'
        return row.get("delete")=="1"

    class Meta:
        model = Book
        fields = ('hash_id','id', 'name','price', 'author', 'published_field', 'categories' )

        # import_id_fields is concerned with "What column(s) in my CSV file make a row unique?"
        # get_instance() is concerned with "How do I take the value from that unique CSV column and
        # use it to find an object in my database?"
        import_id_fields = ('hash_id',)     # To uniquely identify Book
        # The default get_instance() logic constructs a database query based directly on the import_id_fields.
        # It tries to execute the following --
        # --This is what the library attempts internally when it sees -- import_id_fields = ('hash_id')
        # --Book.objects.get(hash_id=''aeed497bc5c30...')

        # import_order = ('id', 'price')
        # export_order = ('id', 'price', 'author', 'name')
        # You MUST enable this switch for the (after_import()) feature to work.
        store_instance = True
        # All widgets with foreign key functions use them.
        # use_natural_foreign_keys = True


@admin.register(Book)
class BookAdmin(ImportExportModelAdmin):
    resource_class = BookResource


# ----------------- CUSTOMIZE IMPORT FORMS -------------------
# The initial form where the user uploads a file and selects additional options (like the author).
class CustomImportForm(ImportForm):
    author = forms.ModelChoiceField(
        queryset=Author.objects.all(),
        required=True)


# The confirmation form where the user reviews the data before finalizing the import.
class CustomConfirmImportForm(ConfirmImportForm):
    author = forms.ModelChoiceField(
        queryset=Author.objects.all(),
        required=True)


class CustomExportForm(ExportForm):
    """Customized ExportForm, with author field required."""
    author = forms.ModelChoiceField(
        queryset=Author.objects.all(),
        required=True)


# Customizing ModelAdmin
class CustomBookAdmin(ImportMixin, admin.ModelAdmin):
    resource_class = [BookResource]
    # Tells Django to use the custom import form with the author field.
    import_form_class = CustomImportForm
    # Uses the custom confirmation form.
    confirm_form_class = CustomConfirmImportForm
    # Use the custom export form instead of the default export form.
    export_form_class = CustomExportForm

    # This method ensures the `author` selected in the initial import form is passed to
    # the confirmation form.
    def get_confirm_form_initial(self, request, import_form):
        # import_form is an instance of the form class defined by import_form_class, not
        # the form class itself.
        initial = super().get_confirm_form_initial(request, import_form)
        # initial = super().get_confirm_form_initial() gets the default initial values from ImportMixin.


        # Pass on the 'author' value from the import form to the confirm firm (if provided).
        if import_form:
            initial['author'] = import_form.cleaned_data['author'].id
        return initial
        # After this method runs, django-import-export uses the returned initial dictionary to instantiate
        # the confirmation form (e.g., CustomConfirmImportForm).

        # Why Returning initial Works
        # The initial dictionary is the standard way Django forms receive default values. By returning it
        # from get_confirm_form_initial(), you’re explicitly telling the confirmation form what values to start with.
        # In this case, adding 'author' to initial ensures the confirmation form’s author field is prefilled with
        # the value from import_form.cleaned_data['author'].



    # Saving the Author with the EBook
    # To actually associate the selected `author` with each imported Ebook instance, two more
    # methods are added to CustomBookAdmin
    def get_import_data_kwargs(self, request, *args, **kwargs):
        """
        Prepare kwargs for import_data
        """
        form = kwargs.get("form", None)
        if form and hasattr(form, "cleaned_data"):
            kwargs.update({"author": form.cleaned_data.get("author", None)})
        return kwargs

    def after_init_instance(self, instance, new, row, **kwargs):
        if "author" in kwargs:
            instance.author = kwargs["author"]
            # `instance` is an object of the EBook model,
            # this line takes the author from kwargs (provided via the form)
            # and assigns it to the author field of the EBook instance. This happens for each EBook being imported,
            # ensuring that every imported ebook is linked to the selected author.

# The selected `author` is now set as an attribute on the instance object. When the instance
# is saved, then the author is set as a foreign key relation to the instance.

# What is kwargs?
# kwargs is a dictionary that carries extra data through the import process. In this case,
# kwargs["author"] contains the author selected by the user in the import form.

    # Overrides a method from the base class to customize the keyword arguments (kwargs)
    # passed to the resource class.
    def get_export_resource_kwargs(self, request, **kwargs):
        # Retrieve the export_form from the kwargs (this is the submitted `CustomExportForm`)
        export_form = kwargs.get("export_form")
        if export_form and hasattr(export_form, "cleaned_data"):
            kwargs.update(author_id=export_form.cleaned_data["author"].id)
        return kwargs
    # This ensures that the selected author's ID is passed to the BookResource when it's instantiated.


# Registering the Admin
admin.site.register(Book, CustomBookAdmin)


