from django.contrib import admin
from import_export import resources
from .models import Book, Author, Category
from import_export.fields import Field
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import DateWidget, IntegerWidget, ForeignKeyWidget, ManyToManyWidget


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
    def clean(self, value, row=None, **kwargs):
        # The value parameter holds the data from the cell in the imported file.
        # We first check if this value is empty, None, or otherwise "falsy".
        if not value:
            # If the value is missing, we'll use 'NA' as the author's name.
            # It fetches the Author named 'NA' if it already exists, or creates
            # it if it doesn't, all in a single database transaction.
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

    author = Field(attribute='author',column_name='author',
                   widget=AuthorForeignKeyWidget(Author, field='name'))
    # This is implemented as a Model.objects.get() query, so if the instance in not uniquely identifiable based
    # on the given arg, then the import process will raise either DoesNotExist or MultipleObjectsReturned errors.
    # Example: The query Author.objects.get(name="J.K. Rowling") is needed during CSV import because
    # the Book.author field is a ForeignKey that requires an existing Author instance, not a string like "J.K. Rowling".

    categories = Field(attribute='categories', column_name='categories',
                       widget=ManyToManyWidget(Category, field='name', seperator='|'))

    # This method runs for every row after it's saved.
    def after_import_row(self, row, row_result, **kwargs):
        # Consider checking for None values, which might lead to an error
        original = row_result.original
        instance = row_result.instance

        # if getattr(row_result.original, "published") is None \
        #     and getattr(row_result.instance, "published") is not None:
        # The above logic is replaced as:
        if original is not None and original.published is None \
            and instance is not None and instance.published is None:
            # import value is different from stored value.
            # execute your custom logic here, like sending an email.
            print(f"Workflow triggered for books: {row_result.instance.name}")
            # send_new_release notification(row_result.instance)

        # Diagnostic information for troubleshooting
        elif instance is not None and hasattr(instance, 'published') and  instance.published is not None:
            # The date field is None, which might indicate parsing failure
            raw_date_value = row.get('published_field', 'NOT_FOUND')
            print(f"Warning: Date parsing may have failed for '{instance.name}'. Raw value:'{raw_date_value}'")

        else:
            # Log what we actually received for debugging
            print(f"Debug - Original: {original}, Instance: {instance}")
            if instance:
                print(f"Instance published: {getattr(instance, 'published', 'MISSING')}")

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

    def for_delete(self, row, instance):
        # Delete if 'delete' column has value '1'
        return row.get("delete")=="1"

    class Meta:
        model = Book
        fields = ('id', 'name', 'price', 'author', 'published_field')
        import_order = ('id', 'price')
        export_order = ('id', 'price', 'author', 'name')
        # You MUST enable this switch for the (after_import()) feature to work.
        store_instance = True


@admin.register(Book)
class BookAdmin(ImportExportModelAdmin):
    resource_class = BookResource
