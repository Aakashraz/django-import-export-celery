import hashlib

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
    model = Author
    field = 'name'

    def __init__(self, publisher_id, **kwargs):
        super().__init__(self.model, field=self.field, **kwargs)
        self.publisher_id = publisher_id

    # Customize Relation lookup
    def get_queryset(self, value, row, *args, **kwargs):
        return self.model.objects.filter(publisher_id=self.publisher_id)


    def clean(self, value, row=None, **kwargs):
        # The value parameter holds the data from the cell in the imported file.
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
    hash_id = Field(column_name='hash_id', attribute=None)      # Define Dynamic Field

    # author = Field(attribute='author',column_name='author',
    #                widget=AuthorForeignKeyWidget(Author, field='name'))
    # For Dynamically setting/accessing the author field with the publisher_id
    def __init__(self, publisher_id):
        super().__init__()
        self.fields["author"] = Field(
            attribute="author",
            column_name='author',
            widget=AuthorForeignKeyWidget(publisher_id),    # No use_natural_foreign_keys=True
            # Passes publisher_id to the AuthorForeignKeyWidget, enabling runtime customization.
        )

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
