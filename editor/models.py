#Copyright 2012 Newcastle University
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
import uuid
import os
import json
from datetime import datetime
import codecs
try:
  # For Python > 2.7
  from collections import OrderedDict
except ImportError:
  # For Python < 2.6 (after installing ordereddict)
  from ordereddict import OrderedDict

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import Q
from django.forms import model_to_dict
from uuslug import slugify

from taggit.managers import TaggableManager

from examparser import ExamParser, ParseError, printdata

from jsonfield import JSONField

PUBLIC_ACCESS_CHOICES = (('hidden','Hidden'),('view','Public can view'),('edit','Public can edit'))
USER_ACCESS_CHOICES = (('view','Public can view'),('edit','Public can edit'))

class ControlledObject:

    def can_be_viewed_by(self,user):
        accept_levels = ('view','edit')
        return (self.public_access in accept_levels) or (user.is_superuser) or (self.author==user) or (self.get_access_for(user) in accept_levels)

    def can_be_edited_by(self, user):
        return self.public_access=='edit' or (user.is_superuser) or (self.author==user) or self.get_access_for(user)=='edit'

class NumbasObject:

    def get_parsed_content(self):
        if self.content:
            parser = ExamParser()
            self.parsed_content = parser.parse(self.content)
            self.name = self.parsed_content['name']
        elif self.name:
            self.content = '{name: %s}' % self.name
            self.parsed_content = {'name': self.name}

        self.extensions = self.parsed_content.get('extensions',[])
        self.metadata = self.parsed_content.get('metadata',self.metadata)

        return self.parsed_content

    def set_name(self,name):
        self.name = name
        if self.content:
            data = ExamParser().parse(self.content)
            data['name'] = name
            self.content = printdata(data)
        self.save()


#check that the .exam file for an object is valid and defines at the very least a name
def validate_content(content):
    try:
        data = ExamParser().parse(content)
        if not 'name' in data:
            raise ValidationError('No "name" property in content.')
    except ParseError as err:
        raise ValidationError(err)

class Extension(models.Model):
    name = models.CharField(max_length=200,help_text='A readable name, to be displayed to the user')
    location = models.CharField(max_length=200,help_text='The location of the extension on disk')
    url = models.CharField(max_length=300,blank=True,help_text='Address of a page about the extension')

    def __unicode__(self):
        return self.name

    def as_json(self):
        d = model_to_dict(self)
        return json.dumps(d)

class Image( models.Model ):
    title = models.CharField( max_length=255 ) 
    image = models.ImageField( upload_to='images/', max_length=255) 

    @property 
    def data_url( self ):
        try:
            img = open( self.image.path, "rb") 
            data = img.read() 
            return "data:image/jpg;base64,%s" % codecs.encode(data,'base64')[:-1]
    
        except IOError as e:
            print(e)
            return self.image.url

    @property
    def resource_url(self):
        return 'resources/%s' % self.image.name

    def delete(self,*args,**kwargs):
        self.image.delete(save=False)
        super(Image,self).delete(*args,**kwargs)

    def as_json(self):
        return {
            'url': self.resource_url,
            'name': self.title,
            'pk': self.pk,
            'delete_url': reverse('delete_resource',args=(self.pk,)),
        }

    def summary(self):
        return json.dumps(self.as_json()),

class QuestionManager(models.Manager):
    def viewable_by(self,user):
        if user.is_superuser:
            return self.all()
        else:
            return list(self.all().filter(public_view=True)).extend(user.viewable_questions.all())


class Question(models.Model,NumbasObject,ControlledObject):
    
    """Model class for a question.
    
    Many-to-many relation with Exam through ExamQuestion.
    
    """

    objects = QuestionManager()
    
    name = models.CharField(max_length=200,default='Untitled Question')
    theme = 'question'
    slug = models.SlugField(max_length=200,editable=False,unique=False)
    author = models.ForeignKey(User,related_name='own_questions')
    filename = models.CharField(max_length=200, editable=False,default='')
    content = models.TextField(blank=True,validators=[validate_content])
    metadata = JSONField(blank=True)
    created = models.DateTimeField(auto_now_add=True,default=datetime.fromtimestamp(0))
    last_modified = models.DateTimeField(auto_now=True,default=datetime.fromtimestamp(0))
    resources = models.ManyToManyField(Image,blank=True)

    public_access = models.CharField(default='view',editable=True,choices=PUBLIC_ACCESS_CHOICES,max_length=6)
    access_rights = models.ManyToManyField(User, through='QuestionAccess', blank=True, editable=False,related_name='accessed_questions+')

    PROGRESS_CHOICES = [
        ('in-progress','Writing in progress'),
        ('not-for-use','Not for general use'),
        ('testing','Undergoing testing'),
        ('ready','Tested and ready to use'),
    ]
    progress = models.CharField(max_length=15,editable=True,default='in-progress',choices=PROGRESS_CHOICES)

    tags = TaggableManager()

    class Meta:
      ordering = ['name']

    def __unicode__(self):
        return 'Question "%s"' % self.name
    
    def save(self, *args, **kwargs):
        NumbasObject.get_parsed_content(self)

        self.slug = slugify(self.name)

        self.progress = self.parsed_content.get('progress','in-progress')

        super(Question, self).save(*args, **kwargs)

        if 'tags' in self.parsed_content:
           self.tags.set(*self.parsed_content['tags'])


    def delete(self, *args, **kwargs):
        super(Question,self).delete(*args, **kwargs)

    def get_filename(self):
        return 'question-%i-%s' % (self.pk,self.slug)

    def as_source(self):
        self.get_parsed_content()
        data = OrderedDict([
            ('name',self.name),
            ('extensions',self.extensions),
            ('resources',[[i.image.name,i.image.path] for i in self.resources.all()]),
            ('navigation',{'allowregen': 'true', 'showfrontpage': 'false', 'preventleave': False}),
            ('questions',[self.parsed_content])
        ])
        return printdata(data)

    def as_json(self):
        d = model_to_dict(self)
        d['metadata'] = self.metadata
        d['tags'] = [ti.tag.name for ti in d['tags']]
        d['resources'] = [res.as_json() for res in self.resources.all()]
        return json.dumps(d)

    def summary(self, user=None):
        """return id, name and url, enough to identify a question and say where to find it"""
        obj = {
            'id': self.id, 
            'name': self.name, 
            'progress': self.progress,
            'progressDisplay': self.get_progress_display(),
            'metadata': self.metadata,
            'created': str(self.created),
            'last_modified': str(self.last_modified), 
            'author': self.author.get_full_name(), 
            'url': reverse('question_edit', args=(self.pk,self.slug,)),
            'deleteURL': reverse('question_delete', args=(self.pk,self.slug)),
        }
        if user:
            obj['canEdit'] = self.can_be_edited_by(user) 
        return obj

    def set_access(self,user,access_level):
        access = QuestionAccess(user=user,question=self,access=access_level)
        access.save()

    def get_access_for(self,user):
        if user.is_anonymous():
            return 'none'
        try:
            question_access = QuestionAccess.objects.get(question=self,user=user)
            return question_access.access
        except QuestionAccess.DoesNotExist:
            return 'none'


class QuestionAccess(models.Model):
    question = models.ForeignKey(Question)
    user = models.ForeignKey(User)
    access = models.CharField(default='view',editable=True,choices=USER_ACCESS_CHOICES,max_length=6)


class Exam(models.Model,NumbasObject,ControlledObject):
    
    """Model class for an Exam.
    
    Many-to-many relation with Question through ExamQuestion.
    
    """
    
    questions = models.ManyToManyField(Question, through='ExamQuestion',
                                       blank=True, editable=False)
    name = models.CharField(max_length=200,default='Untitled Exam')
    theme = models.CharField(max_length=200,default='default')
    locale = models.CharField(max_length=200,default='en-GB')
    slug = models.SlugField(max_length=200,editable=False,unique=False)
    author = models.ForeignKey(User,related_name='own_exams')
    filename = models.CharField(max_length=200, editable=False,default='')
    content = models.TextField(blank=True, validators=[validate_content])
    created=models.DateTimeField(auto_now_add=True,default=datetime.fromtimestamp(0))
    last_modified=models.DateTimeField(auto_now=True,default=datetime.fromtimestamp(0))
    metadata = JSONField(blank=True)

    public_access = models.CharField(default='view',editable=True,choices=PUBLIC_ACCESS_CHOICES,max_length=6)
    access_rights = models.ManyToManyField(User, through='ExamAccess', blank=True, editable=False,related_name='accessed_exams+')

    class Meta:
      ordering = ['name']

    def __unicode__(self):
        return 'Exam "%s"' %self.name
    
    def get_questions(self):
        return self.questions.order_by('examquestion')

    def set_questions(self,question_list=None,**kwargs):
        """ 
            Set the list of questions for this exam. 
            question_list is an ordered list of question IDs
        """

        if 'question_ids' in kwargs:
            question_list = [Question.objects.get(pk=pk) for pk in kwargs['question_ids']]

        self.questions.clear()
        for order,question in enumerate(question_list):
            exam_question = ExamQuestion(exam=self,question=question, qn_order=order)
            exam_question.save()
    
    def save(self, *args, **kwargs):
        NumbasObject.get_parsed_content(self)
        
        self.slug = slugify(self.name)
            
        super(Exam, self).save(*args, **kwargs)

    def get_filename(self):
        return 'exam-%i-%s' % (self.pk,self.slug)
        
    def as_source(self):
        parser = ExamParser()
        data = parser.parse(self.content)
        extensions = []
        resources = []
        for q in self.get_questions():
            q.get_parsed_content()
            extensions += q.extensions
            resources += q.resources.all()
        data['extensions'] = list(set(extensions))
        data['name'] = self.name
        data['questions'] = [parser.parse(q.content) for q in self.get_questions()]
        data['resources'] = [[i.image.name,i.image.path] for i in set(resources)]
        return printdata(data)
        
    def summary(self, user=None):
        """return enough to identify an exam and say where to find it, along with a description"""
        obj = {
            'id': self.id, 
            'name': self.name, 
            'metadata': self.metadata,
            'created': str(self.created), 
            'last_modified': str(self.last_modified), 
            'author': self.author.get_full_name(), 
            'url': reverse('exam_edit', args=(self.pk,self.slug,)),
            'deleteURL': reverse('exam_delete', args=(self.pk,self.slug)),
        }
        if user:
            obj['canEdit'] = self.can_be_edited_by(user) 
        return obj

    def set_access(self,user,access_level):
        access = ExamAccess(user=user,exam=self,access=access_level)
        access.save()

    def get_access_for(self,user):
        if user.is_anonymous():
            return 'none'
        try:
            exam_access = ExamAccess.objects.get(exam=self,user=user)
            return exam_access.access
        except ExamAccess.DoesNotExist:
            return 'none'

class ExamAccess(models.Model):
    exam = models.ForeignKey(Exam)
    user = models.ForeignKey(User)
    access = models.CharField(default='view',editable=True,choices=USER_ACCESS_CHOICES,max_length=6)
        
        
class ExamQuestion(models.Model):
    
    """Model class linking exams and questions."""
    
    class Meta:
        ordering = ['qn_order']
        
    exam = models.ForeignKey(Exam)
    question = models.ForeignKey(Question)
    qn_order = models.PositiveIntegerField()
