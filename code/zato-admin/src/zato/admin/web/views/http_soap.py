# -*- coding: utf-8 -*-

"""
Copyright (C) 2011 Dariusz Suchojad <dsuch at gefira.pl>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

# stdlib
import logging
from traceback import format_exc

# Django
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseServerError
from django.shortcuts import render_to_response
from django.template import RequestContext

# lxml
from lxml import etree
from lxml.objectify import Element

# Validate
from validate import is_boolean

# anyjson
from anyjson import dumps

# Zato
from zato.admin.web import invoke_admin_service
from zato.admin.web.forms.http_soap import ChooseClusterForm, CreateForm, EditForm
from zato.admin.web.views import meth_allowed
from zato.common.odb.model import Cluster, HTTPSOAP
from zato.common import zato_namespace, zato_path, ZatoException
from zato.common.util import TRACE1, to_form

logger = logging.getLogger(__name__)

CONNECTION = {
    'channel': 'channel',
    'outgoing': 'outgoing connection',
    }

CONNECTION_PLURAL = {
    'channel': 'channels',
    'outgoing': 'outgoing connections',
    }

TRANSPORT = {
    'plain': 'Plain HTTP',
    'soap': 'SOAP',
    }

def _get_edit_create_message(params, prefix=''):
    """ Creates a base document which can be used by both 'edit' and 'create' actions
    for channels and outgoing connections.
    """
    zato_message = Element('{%s}zato_message' % zato_namespace)
    zato_message.data = Element('data')
    zato_message.data.id = params.get('id')
    zato_message.data.cluster_id = params['cluster_id']
    zato_message.data.name = params[prefix + 'name']
    zato_message.data.is_active = bool(params.get(prefix + 'is_active'))
    zato_message.data.connection = params['connection']
    zato_message.data.transport = params['transport']
    zato_message.data.url_path = params[prefix + 'url_path']
    zato_message.data.method = params[prefix + 'method']
    zato_message.data.soap_action = params.get(prefix + 'soap_action', '')
    zato_message.data.soap_version = params.get(prefix + 'soap_version', '')

    return zato_message

def _edit_create_response(id, verb, transport, connection, name):

    return_data = {'id': id,
                   'transport': transport,
                   'message': 'Successfully {0} the {1} {2} [{3}]'.format(
                       verb,
                       TRANSPORT[transport],
                       CONNECTION[connection],
                       name),
                }

    return HttpResponse(dumps(return_data), mimetype='application/javascript')

@meth_allowed('GET')
def index(req):
    zato_clusters = req.odb.query(Cluster).order_by('name').all()
    choose_cluster_form = ChooseClusterForm(zato_clusters, req.GET)
    cluster_id = req.GET.get('cluster')
    connection = req.GET.get('connection')
    transport = req.GET.get('transport')
    items = []

    if not all((connection, transport)):
        log_msg = "Redirecting to / because at least one of ('connection', 'transport') GET parameters was missing"
        logger.debug(log_msg)
        return HttpResponseRedirect('/')

    create_form = CreateForm()
    edit_form = EditForm(prefix='edit')

    if cluster_id and req.method == 'GET':

        cluster = req.odb.query(Cluster).filter_by(id=cluster_id).first()

        zato_message = Element('{%s}zato_message' % zato_namespace)
        zato_message.data = Element('data')
        zato_message.data.cluster_id = cluster_id
        zato_message.data.connection = connection
        zato_message.data.transport = transport

        _, zato_message, soap_response  = invoke_admin_service(cluster, 'zato:http_soap.get-list', zato_message)

        if zato_path('data.item_list.item').get_from(zato_message) is not None:

            for msg_item in zato_message.data.item_list.item:

                id = msg_item.id.text
                name = msg_item.name.text
                is_active = is_boolean(msg_item.is_active.text)
                url_path = msg_item.url_path.text

                method = msg_item.method.text if msg_item.method else ''
                soap_action = msg_item.soap_action.text if msg_item.soap_action else ''
                soap_version = msg_item.soap_version.text if msg_item.soap_version else ''

                item =  HTTPSOAP(id, name, is_active, connection, transport, url_path, method, soap_action, soap_version)
                items.append(item)

    return_data = {'zato_clusters':zato_clusters,
        'cluster_id':cluster_id,
        'choose_cluster_form':choose_cluster_form,
        'items':items,
        'create_form':create_form,
        'edit_form':edit_form,
        'connection':connection,
        'transport':transport,
        'connection_label':CONNECTION[connection],
        'connection_label_plural':CONNECTION_PLURAL[connection],
        'transport_label':TRANSPORT[transport],
        }

    # TODO: Should really be done by a decorator.
    if logger.isEnabledFor(TRACE1):
        logger.log(TRACE1, 'Returning render_to_response [{0}]'.format(return_data))

    return render_to_response('zato/http_soap.html', return_data,
                              context_instance=RequestContext(req))

@meth_allowed('POST')
def create(req):

    cluster = req.odb.query(Cluster).filter_by(id=req.POST['cluster_id']).first()

    try:
        zato_message = _get_edit_create_message(req.POST)
        _, zato_message, soap_response = invoke_admin_service(cluster, 'zato:http_soap.create', zato_message)

        return _edit_create_response(zato_message.data.http_soap.id.text,
                                     'created',
                                     req.POST['transport'],
                                     req.POST['connection'],
                                     req.POST['name'])
    except Exception, e:
        msg = 'Could not create the object, e=[{e}]'.format(e=format_exc(e))
        logger.error(msg)
        return HttpResponseServerError(msg)


@meth_allowed('POST')
def edit(req):

    cluster = req.odb.query(Cluster).filter_by(id=req.POST['cluster_id']).first()

    try:
        zato_message = _get_edit_create_message(req.POST, 'edit-')
        _, zato_message, soap_response = invoke_admin_service(cluster, 'zato:http_soap.edit', zato_message)

        return _edit_create_response(zato_message.data.http_soap.id.text,
                                     'updated',
                                     req.POST['transport'],
                                     req.POST['connection'],
                                     req.POST['edit-name'])

    except Exception, e:
        msg = 'Could not perform the update, e=[{e}]'.format(e=format_exc(e))
        logger.error(msg)
        return HttpResponseServerError(msg)

@meth_allowed('POST')
def delete(req, id, cluster_id):

    cluster = req.odb.query(Cluster).filter_by(id=cluster_id).first()

    try:
        zato_message = Element('{%s}zato_message' % zato_namespace)
        zato_message.data = Element('data')
        zato_message.data.id = id

        _, zato_message, soap_response = invoke_admin_service(cluster, 'zato:http_soap.delete', zato_message)

        return HttpResponse()

    except Exception, e:
        msg = 'Could not delete the object, e=[{e}]'.format(e=format_exc(e))
        logger.error(msg)
        return HttpResponseServerError(msg)