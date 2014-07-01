import numpy as np
import json
import torndb
import random
from numpy import matrix

from util import iter_summary
from document import Document

from linrel import linrel
from data import KwDocData

from pprint import pprint

random.seed(123456)

class Recommender(KwDocData):
    """
    Recommendation engine that handles the recommending stuff
    """
    def recommend_keywords(self, *args, **kwargs):
        raise NotImplementedError

    def recommend_documents(self, *args, **kwargs):
        raise NotImplementedError

class QueryBasedRecommender(Recommender):
    """
    query-based IR system 
    """
    def __init__(self, db, table, *args, **kwargs):
        """
        session: the session object used to retrieve session data
        db: the db connection
        table: the table to query against
        args/kwargs: the matrix and index mapping stuff
        """
        super(QueryBasedRecommender, self).__init__(*args, **kwargs)
        self._db = db
        self._table = table

    def _word_vec(self, words):
        """
        given the words return the word binary vector
        """
        kw_total_num = len(self._kw_ind.keys())
        word_vec = np.zeros((kw_total_num, 1))
        for word in words:
            word_vec[self._kw_ind[word], 0] = 1
        return matrix(word_vec)

    def recommend_keywords(self, rec_docs, kw_num, kw_num_from_docs):
        """
        Given the recommended documents, rec_docs, as well as the number of keywords, kw_num_from_docs to be sampled from the documents,

        Param:
        rec_docs: the recommended documents
        kw_num: the number of keywords to be recommended
        kw_num_from_docs: number of keywords to be sampled from the docs
        weighted: using TfIdf weight for the above sampling or not(**NOT IMPLEMENTED BY NOW**))

        Return:
        recommended keywords as well as the scores(in this case, 0)
        ['kw1', 'kw2', ...], [0,0,0]
        """
        if kw_num_from_docs > kw_num:
            raise ValueError('kw_num_from_docs should be less or equal to kw_num')
            
        #sample kw_num_from_docs from the keywords in the documents, 
        all_kws_from_docs = set([kw 
                                 for doc in rec_docs 
                                 for kw in doc['keywords']])
        
        if len(all_kws_from_docs) <= kw_num_from_docs:
            kws_from_docs = list(all_kws_from_docs)
        else:
            kws_from_docs = random.sample(list(all_kws_from_docs), kw_num_from_docs)

        #get all the documents that have keywords in common with the documents being recommended
        word_vec = self._word_vec(kws_from_docs)
        row_idx, _ = np.nonzero(self._doc2kw_m * word_vec)

        assoc_docs = [self._get_doc(self._doc_ind_r[idx]) 
                      for idx in row_idx.tolist()[0]]
                
        keywords = set([kw for doc in assoc_docs for kw in doc['keywords']])
        remaining_keywords = keywords - set(kws_from_docs)
        
        #sample kw_num - kw_num_from_docs keywords from the above document set
        if len(remaining_keywords) <= kw_num - kw_num_from_docs: #not enough population to sample from..
            print 'Not enouth remaining keywords.. use them all'
            extra_keywords = list(remaining_keywords)
        else:
            extra_keywords = random.sample(list(remaining_keywords), kw_num - kw_num_from_docs)
        
        #return the joined set of keywords
        rec_kws = extra_keywords + kws_from_docs
        return rec_kws, [0] * len(rec_kws)

    def recommend_documents(self, query, top_n):
        """
        Given the query, 
        Return the top_n related documents as well as the scores in the format of:
        ([1,2,3], [.5, .6, .7])
        """
        query_words = query.strip().split()
        #prepare the query word binary column vector        
        word_vec = self._word_vec(query_words)
        
        #get the scores for documents and scort it
        scores = self._doc2kw_m * word_vec
        sorted_scores = sorted(enumerate(np.array(scores.T).tolist()[0]), key = lambda (id, score): score, reverse = True)
        
        #get the top_n documents 
        doc_ids = []
        scores = []
        for ind, score in sorted_scores[:top_n]:
            doc_id = self._doc_ind_r[ind]
            
            doc_ids.append(doc_id)
            scores.append(score)
        
        return doc_ids, scores
        
    def _get_doc(self, doc_id):
        """get document by id from database"""
        sql_temp = 'SELECT id, title, keywords FROM %s WHERE id=%%s' %self._table
        row = self._db.get(sql_temp, doc_id)
        row['keywords'] = json.loads(row['keywords'])
        return Document(row)


def test_query(query):
    from data import kw2doc_matrix    
    table = 'test'
    d_ = kw2doc_matrix(table)
    
    db = torndb.Connection("%s:%s" % ('ugluk', 3306), 'scinet3', 'hxiao', 'xh24206688')
    
    r = QueryBasedRecommender(db, table, **d_)
    doc_ids, scores = r.recommend_documents(query, 2)
    docs = [r._get_doc(doc_id) for doc_id in doc_ids]
    
    pprint(docs)

    kws = r.recommend_keywords(docs, 4, 2)
    pprint(kws)
    

class LinRelRecommender(Recommender): 
    def __init__(self, session, *args):
        """
        session: the session object used to retrieve session data
        args: the matrix and index mapping stuff
        """
        super(LinRelRecommender, self).__init__(*args)
        self._session = session
        
    def generic_recommend(self, K, fb, id2ind_map,
                          mu, c):
        """
        Parameter:
        K: the whole data matrix
        fb: feedbacks, dict
        id2ind_map: mapping from object id to matrix indices
        
        Return:
        the matrix row indices as well as the scores(in descending order)
        and the sorted decomposition of the scores
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

        scores, exploration_scores, exploitation_scores  = linrel(y_t, K_t, K, mu, c) #do the linrel
        
        def add_index_and_sort(matrix):
            """add the row index information and sort """
            return sorted(enumerate(np.array(matrix.T).tolist()[0]), key = lambda (id, score): score, reverse = True)

        sorted_scores =  add_index_and_sort(scores)
        sorted_exploration_scores =  add_index_and_sort(exploration_scores)
        sorted_exploitation_scores =  add_index_and_sort(exploitation_scores)
        
        return sorted_scores, sorted_exploration_scores, sorted_exploitation_scores
        
    def recommend_keywords(self, top_n, mu, c, feedbacks = None ):
        """
        return a list of keyword ids as well as their scores
        """
        if feedbacks:#if given, update
            self._session.kw_feedbacks = feedbacks
            self._session.kw_fb_hist = feedbacks
        else:
            self._session.kw_fb_hist = {}

        scores, explr_scores, explt_scores = self.generic_recommend(self._kw2doc_m, self._session.kw_feedbacks, self._kw_ind,
                                                                                 mu, c)
        
        id_with_scores = [(self._kw_ind_r[ind], score) for ind,score in scores]
        id_with_explr_scores = [(self._kw_ind_r[ind], score) for ind,score in explr_scores]
        id_with_explt_scores = [(self._kw_ind_r[ind], score) for ind,score in explt_scores]
        
        top_ids_with_scores = [(self._kw_ind_r[ind], score) for ind,score in scores[:top_n]]
        top_ids = [self._kw_ind_r[ind] for ind,_ in scores[:top_n]]
        
        #self._session.kw_ids = top_ids #it might not be necessary

        # the history also
        self._session.kw_score_hist = dict(id_with_scores)
        self._session.kw_explr_score_hist = dict(id_with_explr_scores)
        self._session.kw_explt_score_hist = dict(id_with_explt_scores) 
                
        return zip(*top_ids_with_scores)
        
    def recommend_documents(self, top_n, mu, c, feedbacks = None):
        """
        return a list of document ids as well as the scores
        """
        if feedbacks:#if given, update
            self._session.doc_feedbacks = feedbacks
            self._session.doc_fb_hist = feedbacks
        else:
            self._session.doc_fb_hist = {}

        scores, explr_scores, explt_scores = self.generic_recommend(self._doc2kw_m, self._session.doc_feedbacks, self._doc_ind,
                                                                                 mu, c)
                
        top_ids_with_scores = [(self._doc_ind_r[ind], score) for ind, score in scores[:top_n]]
        top_ids = [self._doc_ind_r[ind] for ind, _ in scores[:top_n]]
        
        # self._session.doc_ids = top_ids

        # the history also
        id_with_scores = [(self._doc_ind_r[ind], score) for ind,score in scores]
        id_with_explr_scores = [(self._doc_ind_r[ind], score) for ind,score in explr_scores]
        id_with_explt_scores = [(self._doc_ind_r[ind], score) for ind,score in explt_scores]
        
        self._session.doc_score_hist = dict(id_with_scores)
        self._session.doc_explr_score_hist = dict(id_with_explr_scores)
        self._session.doc_explt_score_hist = dict(id_with_explt_scores) 
        

        return zip(*top_ids_with_scores)
            
def main():
    import  redis
    from session import RedisRecommendationSessionHandler
    from data import kw2doc_matrix
    top_n = 2
    mu = 1
    c = 1
    
    table = 'test'
    db = torndb.Connection("%s:%s" % ('ugluk', 3306), 'scinet3', 'hxiao', 'xh24206688')    

    redis_conn = redis.StrictRedis(host='ugluk', port='6379', db='test')
    #init session
    s = RedisRecommendationSessionHandler.get_session(redis_conn)
    
    d_ = kw2doc_matrix('test')
    linrel_r = LinRelRecommender(s, d_._kw_ind, d_._doc_ind, d_._kw2doc_m, d_._doc2kw_m)
    query_r = QueryBasedRecommender(db, table, d_._kw_ind, d_._doc_ind, d_._kw2doc_m, d_._doc2kw_m)
    
    kw_dict = dict([(kw, kw) for kw in d_._kw_ind.keys()]) #kw_id -> kw
    doc_dict = dict([(doc_id, query_r._get_doc(doc_id)) for doc_id in d_._doc_ind.keys()]) #doc_id -> doc

    query = raw_input('Your query:')
    doc_ids, scores = query_r.recommend_documents(query, top_n)
    docs = [query_r._get_doc(doc_id) for doc_id in doc_ids]
    kw_ids, scores = query_r.recommend_keywords(docs, 4, 2)
    
    print "Recommended documents:"
    for doc in docs:
        print doc

    print "Recommended keywords:"
    for kw in kw_ids:
        print kw,
    print 
                
    linrel_r._session.doc_ids = doc_ids
    linrel_r._session.kw_ids = kw_ids
    
    while True:
        kw_fb_str = raw_input('Please give some feedback for keywords(in format like kw:score,kw:score \n')
        kw_feedbacks = {}
        for seg in kw_fb_str.split(','):
            kw, score = seg.split(':') 
            score = float(score.strip())
            kw_feedbacks[kw.strip()] = score
            
        doc_fb_str = raw_input('Please give some feedback for documents(in the JSON format or numbers separated by space)\n')
        doc_feedbacks = {}
        for seg in doc_fb_str.split(','):
            doc_id, score = seg.split(':') 
            doc_id = int(doc_id)
            score = float(score.strip())
            doc_feedbacks[doc_id] = score
        
        kw_ids, scores = linrel_r.recommend_keywords(top_n, mu, c, kw_feedbacks)
        doc_ids, scores = linrel_r.recommend_documents(top_n, mu, c, doc_feedbacks)

        #print the summary
        iter_summary(kw_dict = kw_dict,
                     doc_dict = doc_dict,
                     **s.data)
        
        print "Recommended documents:"
        for doc_id in doc_ids:
            doc = query_r._get_doc(doc_id)
            print doc

        print "Recommended keywords:"
        for kw in kw_ids:
            print kw,
        print 
    
if __name__ == "__main__":
    #test_query('python redis')
    # test_linrel()
    main()
