import random

import numpy as np
from numpy import matrix
from collections import OrderedDict
from types import IntType, FloatType

from scinet3.data import FeatureMatrixAndIndexMapping
from scinet3.model import (Document, Keyword)
from scinet3.modellist import (DocumentList, KeywordList)

from scinet3.rec_engine.base import Recommender
from scinet3.linrel import linrel

random.seed(123456)

class LinRelRecommender(Recommender): 
    def generic_rank(self, K, fb, 
                     id2ind_map,ind2id_map,
                     mu, c):
        """
        Generic object(document/keyword in our case) ranking using LinRel.
        
        Params:
        K: matrix, the whole data matrix
        fb: dict(integer->float), feedbacks
        id2ind_map: dict(integer->integer), mapping from object id to matrix indices
        ind2id_map: dict(integer->integer), mapping from matrix row index to object id
        mu, c: the LinRel parameters
        
        Return:
        (
        OrderedDict(integer -> float): object id, score, 
        Ordereddict(integer -> float):  object id, exploitation score, 
        Ordereddict(integer -> float):  object id, exploration score
        )
        
        Dict items order by score in descending order
        """
        ids = fb.keys()
        def submatrix():
            idx_in_K = [id2ind_map[id] for id in ids]
            K_sub = K[idx_in_K, :]
            return K_sub
        
        def fb_vec():
            y_t = matrix([fb.get(id, 0) for id in ids]).T
            return y_t
        
        #prepare the matrices
        K_t = submatrix()
        y_t = fb_vec()

        scores, exploitation_scores, exploration_scores  = linrel(y_t, K_t, K, mu, c) #do the linrel
        
        def make_dict(matrix):
            """
            add the row index
            make it into a sorted dict.
            Key: object id
            """
            sorted_tuple = sorted(enumerate(np.array(matrix.T).tolist()[0]), key = lambda (id, score): score, reverse = True)
            
            return OrderedDict([(ind2id_map[ind], score)
                         for ind, score in sorted_tuple])

        scores =  make_dict(scores)
        exploitation_scores =  make_dict(exploitation_scores)
        exploration_scores =  make_dict(exploration_scores)
        
        return scores, exploitation_scores, exploration_scores
    
    def _filter_objs(self, filters, **kwargs):
        """
        We shall do some filtering here:
        select only the objects which passes at least one of the filters

        Return:
        the filtered list of objects
        """
        sel_objs = set()
        for filter_func in filters:
            sel_objs |= set(filter_func(**kwargs))
            
        return list(sel_objs)
        
    def _submatrix_and_indexing(self, row_objs, col_objs, obj_feature_matrix, row_obj2ind_map, col_obj2ind_map):
        """
        Return the submatrix and associated index mapping
        
        ----------------------
        |                    | 
        |     -------------  |
        |     |  we want  |  |
        |     |   this    |  |
        |     -------------  |
        |                    |
        |                    |
        |                    |
        ----------------------
        
        Params:
        row_objs: list of Model, the ids of the row objects to be included in the submatrix
        col_objs: list of Model, the ids of the column objects to be included in the submatrix
        obj_feature_matrix: matrix,  the feature matrix for the whole dataset
        row_obj2ind_map: dict of (integer, integer), the row-object-to-matrix-index mapping
        row_ind2obj_map: dict of (integer, integer), the reserse mapping the above one
        
        Return:
        - the feature matrix concerning only the objects
        - the object to matrix index mapping
        - the inverse index to object mapping
        """
        row_obj_indx = [row_obj2ind_map[obj.id] for obj in row_objs]
        col_obj_indx = [col_obj2ind_map[obj.id] for obj in col_objs]
        
        # get the sub matrix
        # the following way of submatrix slicing is from:
        # http://stackoverflow.com/questions/21060995/submatrix-in-scipy
        submatrix = obj_feature_matrix.tocsr()[row_obj_indx, :].tocsc()[:, col_obj_indx]
        
        obj2ind_submap = dict([(obj.id, ind) for obj, ind in zip(row_objs, xrange(len(row_objs)))])
        ind2obj_submap = dict([(ind, obj.id) for obj, ind in zip(row_objs, xrange(len(row_objs)))])

        return submatrix, obj2ind_submap, ind2obj_submap

    def add_score_history(self, kw_or_doc, ind_map_r, ind_with_scores, ind_with_explr_scores, ind_with_explt_scores):
        id_with_scores = [(ind_map_r[ind], score) for ind,score in ind_with_scores]
        id_with_explr_scores = [(ind_map_r[ind], score) for ind,score in ind_with_explr_scores]
        id_with_explt_scores = [(ind_map_r[ind], score) for ind,score in ind_with_explt_scores]
        
        if kw_or_doc == "keywords":
            self._session.kw_score_hist = dict(id_with_scores)
            self._session.kw_explr_score_hist = dict(id_with_explr_scores)
            self._session.kw_explt_score_hist = dict(id_with_explt_scores)
        elif kw_or_doc == "documents":
            self._session.doc_score_hist = dict(id_with_scores)
            self._session.doc_explr_score_hist = dict(id_with_explr_scores)
            self._session.doc_explt_score_hist = dict(id_with_explt_scores)
        else:
            raise 
        
    def recommend_keywords(self, fmim,
                           session, top_n, mu, c, 
                           sampler=None):
        """
        fmim: FeatureMatrixAndIndexMapping, the fmim for the sub-matrix        
        session: Session,
        top_n: how many kws are returned
        mu,c: float, the parameters for LinRel algorithm
        
        Return
        KeywordList: a list of keyword ids as well as their scores
        """        
        kws = Keyword.get_many(fmim.kw_ind.keys())
        fbs = dict([(kw.id, kw.fb(session)) for kw in kws])
        
        id_with_scores, id_with_explt_scores, id_with_explr_scores = self.generic_rank(fmim.kw2doc_m, fbs, 
                                                                                       fmim.kw_ind, fmim.kw_ind_r,
                                                                                       mu, c)
        
        kws = []
        for kw_id, score in id_with_scores.items()[:top_n]:
            kw = Keyword.get(kw_id)
            kw['score'] = score
            kw['recommended'] = True
            kws.append(kw)
            
        return kws
        
    def recommend_documents(self, fmim,
                            session, top_n, mu, c, 
                            sampler = None):
        """
        return a list of document ids as well as the scores
        """
        docs = Document.get_many(fmim.doc_ind.keys())
        fbs = dict([(doc.id, doc.fb(session)) for doc in docs])
        
        id_with_scores, id_with_explt_scores, id_with_explr_scores = self.generic_rank(fmim.doc2kw_m, fbs, 
                                                                                       fmim.doc_ind,fmim.doc_ind_r,
                                                                                       mu, c)
        docs = []
        for doc_id, score in id_with_scores.items()[:top_n]:
            doc = Document.get(doc_id)
            doc["score"] = score
            doc['recommended'] = True
            docs.append(doc)

        return docs
        
    def recommend(self, session, 
                  recom_kw_num = None, recom_doc_num = None, 
                  linrel_kw_mu = None, linrel_kw_c = None, linrel_doc_mu = None, linrel_doc_c = None,
                  kw_filters = None, doc_filters = None):
        """
        Params:
        session: Session, the session used
        (optional) recom_kw_num, recom_doc_num: integer, number of keywords/documents to be recommended
        (optional) linrel_kw_mu, linrel_kw_c, linrel_doc_mu, linrel_doc_c: float,
                   linrel parameters for keyword/document recommendation
        
        (optional) kw_filters,doc_filters: list of filters to be applied to keywords/documents recommendation
        
        Return:
        (list of Document, list of Keyword)
        """                
        # do some filtering and 
        #get the sub matrix as well as mapping
        kw_filters = kw_filters or self.kw_filters
        doc_filters = doc_filters or self.doc_filters
        
        if kw_filters:
            print "filtering keywords...."
            filtered_kws = self._filter_objs(kw_filters, kws = Keyword.all_kws)
            print "%d / %d keywords" %(len(filtered_kws), len(Keyword.all_kws))
            
        else: # no filter is invovled
            print "no keyword filter is used"
            filtered_kws = Keyword.all_kws

        if doc_filters:
            print "filtering documents...."
            filtered_docs = self._filter_objs(doc_filters, docs = Document.all_docs)
            
            print "%d / %d documents" %(len(filtered_docs), len(Document.all_docs))
        else: # no filter is invovled
            print "no document filter is used"
            filtered_docs = Document.all_docs
        
        
        kw2doc_submat, kw_ind_map, kw_ind_map_r = self._submatrix_and_indexing(filtered_kws, filtered_docs, self.kw2doc_m, self.kw_ind, self.doc_ind)
        doc2kw_submat, doc_ind_map, doc_ind_map_r = self._submatrix_and_indexing(filtered_docs, filtered_kws, self.doc2kw_m, self.doc_ind, self.kw_ind)
        
        print "document2keyword matrix shape=", doc2kw_submat.shape
        
        fmim = FeatureMatrixAndIndexMapping(kw_ind_map, doc_ind_map, kw2doc_submat, doc2kw_submat, kw_ind_map_r, doc_ind_map_r)
        
        #do the recommendation
        rec_kws = self.recommend_keywords(fmim,
                                          session, recom_kw_num or self.recom_kw_num, 
                                          linrel_kw_mu or self.linrel_kw_mu, linrel_kw_c or self.linrel_kw_c)
        
        rec_docs = self.recommend_documents(fmim,
                                            session, recom_doc_num or self.recom_doc_num, 
                                            linrel_doc_mu or self.linrel_doc_mu, linrel_doc_c or self.linrel_doc_c)
        
        #get the associated keywords
        assoc_kws = self.associated_keywords_from_docs(rec_docs, rec_kws)
        
        return DocumentList(rec_docs), KeywordList(rec_kws + assoc_kws)

    def __init__(self, recom_kw_num, recom_doc_num,  #recommendation number
                 linrel_kw_mu, linrel_kw_c, linrel_doc_mu, linrel_doc_c, #linrel parameters
                 kw_filters = None, doc_filters = None, #filters
                 kw_samplers = None, doc_samplers = None, #samplers
                 *args, **kwargs):
        """
        Params:
        recom_kw_num, recom_doc_num: integer, number of keywords/documents to be recommended
        linrel_kw_mu, linrel_kw_c, linrel_doc_mu, linrel_doc_c: float, 
            linrel parameters for keyword/document recommendation
        kw_filters,doc_filters: list of filters to be applied to keywords/documents
        
        args: the matrix and index mapping stuff
        """
        
                  
        #type validation
        for attr_name in ["recom_kw_num", "recom_doc_num"]:
            attr = eval(attr_name)
            assert type(attr) is IntType, "%s should be integer, but is %r" %(attr_name, attr)
            
        #assignment
        self.recom_kw_num = recom_kw_num
        self.recom_doc_num = recom_doc_num

        #type validation
        for attr_name in ["linrel_kw_mu", "linrel_kw_c", "linrel_doc_mu", "linrel_doc_c"]:
            attr = eval(attr_name)
            assert type(attr) is FloatType, "%s should be float, but is %r" %(attr_name, attr)
            
        #assignment
        self.linrel_kw_mu = linrel_kw_mu
        self.linrel_kw_c = linrel_kw_c

        self.linrel_doc_mu = linrel_doc_mu
        self.linrel_doc_c = linrel_doc_c
        
        self.kw_filters = kw_filters
        self.doc_filters = doc_filters

        self.kw_samplers = kw_samplers
        self.doc_samplers = doc_samplers
        
        super(LinRelRecommender, self).__init__(*args, **kwargs)
        
    
