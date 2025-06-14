from django.contrib import admin
from import_export import resources
from datasets.models import Book
from import_export.fields import Field
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import DateWidget


class BookResource(resources.ModelResource):
    # If using the fields attribute to declare fields then
    # the declared resource attribute name must appear in the fields list
    published_field = Field(attribute='published', column_name='published_date',
                           widget=DateWidget(format='%Y-%m-%d'))

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
