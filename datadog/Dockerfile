ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
COPY requirements.txt .
RUN pip install -r requirements.txt

WORKDIR /

# Copy data for add-on
COPY data/* /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]