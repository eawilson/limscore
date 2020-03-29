from setuptools import setup

setup(name="limscore",
    version= "0.1",
    description="Core functionallity for building a lims system.",
    url="",
    author="Ed Wilson",
    author_email="edwardadrianwilson@yahoo.co.uk",
    license="MIT",
    packages=["limscore"],
    install_requires=["sqlalchemy",
                      "alembic",
                      "flask",
                      "passlib",
                      "itsdangerous",
                      "pytz",
                      "bcrypt"],
    include_package_data=True,
    zip_safe=True,
    )

